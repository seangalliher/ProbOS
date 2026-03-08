# Phase 6b: Dynamic Intent Discovery

**Goal:** Make the decomposer's intent table self-assembling from the capability registry, so adding a new agent type automatically makes its intents available to the LLM without editing the system prompt.

---

## Context

Right now the decomposer's `SYSTEM_PROMPT` has a **hardcoded intent table**. Every time a new agent type is added (Phase 5 expansion, Phase 6a introspection), someone must manually update the table, add consensus rules, add examples, and add `MockLLMClient` patterns. This violates the original vision's core promise:

> *"No installation. New capability is added by introducing new agent types to the mesh. They self-integrate by broadcasting capabilities and forming connections."*

This phase makes that real. Agents declare their intents as structured metadata. The decomposer assembles its system prompt dynamically from whatever agents are registered. Add a new agent class, and the LLM immediately knows about it.

---

## Deliverables

### 1. Add `IntentDescriptor` type — `src/probos/types.py`

```python
@dataclass
class IntentDescriptor:
    name: str                    # e.g. "read_file"
    params: dict[str, str]       # e.g. {"path": "<absolute_path>"} — param name → description
    description: str             # e.g. "Read file contents"
    requires_consensus: bool = False
    requires_reflect: bool = False
```

### 2. Update `BaseAgent` — Declare intent descriptors

Add a class-level `intent_descriptors: list[IntentDescriptor] = []` on `BaseAgent`. Each agent subclass declares what intents it handles and their parameter schemas.

Update each existing agent with descriptors:

**FileReaderAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="read_file", params={"path": "<absolute_path>"}, description="Read a file and return content"),
    IntentDescriptor(name="stat_file", params={"path": "<absolute_path>"}, description="Get file size, mtime, etc."),
]
```

**FileWriterAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="write_file", params={"path": "<absolute_path>", "content": "..."}, description="Write content to a file", requires_consensus=True),
]
```

**DirectoryListAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="list_directory", params={"path": "<absolute_path>"}, description="List files and directories"),
]
```

**FileSearchAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="search_files", params={"path": "<absolute_path>", "pattern": "<glob>"}, description="Search for files matching pattern"),
]
```

**ShellCommandAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="run_command", params={"command": "<shell_command>"}, description="Execute a shell command", requires_consensus=True),
]
```

**HttpFetchAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="http_fetch", params={"url": "<url>", "method": "GET"}, description="Fetch a URL", requires_consensus=True),
]
```

**IntrospectionAgent:**
```python
intent_descriptors = [
    IntentDescriptor(name="explain_last", params={}, description="Explain what happened in the last request", requires_reflect=True),
    IntentDescriptor(name="agent_info", params={"agent_type": "...", "agent_id": "..."}, description="Get info about a specific agent", requires_reflect=True),
    IntentDescriptor(name="system_health", params={}, description="Get system health assessment", requires_reflect=True),
    IntentDescriptor(name="why", params={"question": "..."}, description="Explain why ProbOS did something", requires_reflect=True),
]
```

**RedTeamAgent, CorruptedFileReaderAgent, SystemHeartbeatAgent:** `intent_descriptors = []` — these don't handle user intents.

### 3. Create `src/probos/cognitive/prompt_builder.py` — Dynamic prompt assembly

**`PromptBuilder`** — assembles the decomposer system prompt dynamically from registered intent descriptors.

Public API:

| Method | Signature | Description |
|---|---|---|
| `build_system_prompt` | `(descriptors: list[IntentDescriptor]) -> str` | Build the full system prompt with a dynamically generated intent table |

Implementation:

- Keep the static preamble (JSON-only instruction, role description) as a constant `PROMPT_PREAMBLE`.
- Keep the response format section as a constant `PROMPT_RESPONSE_FORMAT`.
- **Dynamically generate** the "Available intents" table from the descriptors list. Sort descriptors by `name` alphabetically for deterministic output.
- **Dynamically generate** the consensus rules: "All {intent_name} intents MUST have use_consensus: true" for any descriptor with `requires_consensus=True`. Non-consensus intents get "should have use_consensus: false".
- **Dynamically generate** the reflect rules: any descriptor with `requires_reflect=True` gets mentioned in a reflect instruction.
- Keep the examples as a constant `PROMPT_EXAMPLES` — these demonstrate format, not enumerate capabilities.
- Return the full assembled prompt string.

**Critical constraint:** The output of `build_system_prompt()` given the current set of agent descriptors must be **functionally equivalent** to the current `SYSTEM_PROMPT`. The LLM receives the same information, structured the same way. Existing `MockLLMClient` regex patterns must still match against prompts built with the dynamic builder. If the exact formatting needs to differ slightly, that's fine — but the semantic content (intent names, param schemas, consensus rules, reflect rules, examples, JSON format instructions) must all be present.

### 4. Update `src/probos/cognitive/decomposer.py` — Use dynamic prompts

**a)** Add `_intent_descriptors: list[IntentDescriptor]` attribute on `IntentDecomposer`, defaulting to empty list.

**b)** Add `_prompt_builder: PromptBuilder` attribute, created in `__init__`.

**c)** Add method `refresh_descriptors(descriptors: list[IntentDescriptor]) -> None` — stores the descriptors and is called by the runtime whenever agent pools change.

**d)** In `decompose()`, build the system prompt dynamically:

```python
if self._intent_descriptors:
    system_prompt = self._prompt_builder.build_system_prompt(self._intent_descriptors)
else:
    system_prompt = _LEGACY_SYSTEM_PROMPT  # Fallback for backward compatibility
```

**e)** Keep `REFLECT_PROMPT` as-is (it doesn't depend on intents).

**f)** Rename the current `SYSTEM_PROMPT` to `_LEGACY_SYSTEM_PROMPT` and add a comment: `# Deprecated — kept for backward compatibility when no descriptors are provided`.

### 5. Add `register_agent_type()` to `src/probos/runtime.py`

This method does not currently exist. Add it:

```python
def register_agent_type(self, agent_type: str, agent_class: type) -> None:
    """Register a new agent type and refresh the decomposer's intent descriptors."""
    self.spawner.register(agent_type, agent_class)
    if self.decomposer:
        self.decomposer.refresh_descriptors(self._collect_intent_descriptors())
```

### 6. Update `src/probos/runtime.py` — Collect and sync descriptors at boot

**a)** After all pools are created in `start()`, collect intent descriptors from all registered agent templates:

```python
def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
    """Collect unique intent descriptors from all registered agent templates."""
    seen = set()
    descriptors = []
    for agent_type, agent_class in self.spawner._templates.items():
        for desc in getattr(agent_class, 'intent_descriptors', []):
            if desc.name not in seen:
                seen.add(desc.name)
                descriptors.append(desc)
    return descriptors
```

**b)** Call `self.decomposer.refresh_descriptors(self._collect_intent_descriptors())` after pool creation in `start()`.

### 7. Create tests

See Test Specification below.

---

## Build Order

1. **`IntentDescriptor` type** (`types.py`)
2. **`BaseAgent`** (`agent.py`) — add `intent_descriptors` class var
3. **All agent subclasses** — add `intent_descriptors` to each
4. **`PromptBuilder`** (`prompt_builder.py`) — dynamic prompt assembly
5. **Tests for PromptBuilder** — verify output contains all expected content
6. **`IntentDecomposer`** (`decomposer.py`) — use PromptBuilder, add `refresh_descriptors()`, rename `SYSTEM_PROMPT` to `_LEGACY_SYSTEM_PROMPT`
7. **`register_agent_type()`** on runtime
8. **`_collect_intent_descriptors()`** and `refresh_descriptors()` call in `start()`
9. **Runtime and integration tests**
10. **Run full suite** — `uv run pytest tests/ -v` — all 456 existing + new tests must pass.
11. **Update PROGRESS.md**

---

## Test Specification

### PromptBuilder unit tests — `tests/test_prompt_builder.py`

1. **`test_build_contains_all_current_intents`** — Build prompt with current descriptors (all 11 intents from current agents). Assert it contains every intent name: read_file, stat_file, write_file, list_directory, search_files, run_command, http_fetch, explain_last, agent_info, system_health, why.

2. **`test_consensus_rules_generated`** — Assert prompt contains consensus-true rules for write_file, run_command, http_fetch and consensus-false guidance for read_file, stat_file, list_directory, search_files.

3. **`test_reflect_rules_generated`** — Assert prompt mentions reflect for explain_last, agent_info, system_health, why.

4. **`test_empty_descriptors`** — Build with empty list. Assert prompt still has JSON-only preamble and response format but no intent table entries.

5. **`test_custom_descriptor_appears`** — Add a custom `IntentDescriptor(name="custom_action", params={"name": "..."}, description="Do custom thing")`. Assert "custom_action" appears in the generated prompt with its params and description.

6. **`test_prompt_contains_json_instruction`** — Build prompt, assert it contains "You MUST respond with ONLY a JSON object" (the critical instruction that makes LLM output parseable).

7. **`test_descriptors_sorted_by_name`** — Pass descriptors in reverse order. Assert the intent table in the output is alphabetically sorted.

8. **`test_duplicate_intent_names_deduplicated`** — Pass two descriptors with the same `name`. Assert the intent appears only once in the output.

9. **`test_prompt_contains_examples`** — Assert the prompt contains the fixed example section (examples demonstrate format, not capabilities, so they're static).

10. **`test_prompt_contains_response_format`** — Assert the prompt contains the JSON response schema (intents array, response field, reflect field).

### IntentDescriptor on agents — `tests/test_prompt_builder.py`

11. **`test_all_agents_have_descriptors`** — For each agent class that handles user intents (FileReaderAgent, FileWriterAgent, DirectoryListAgent, FileSearchAgent, ShellCommandAgent, HttpFetchAgent, IntrospectionAgent), assert `intent_descriptors` is non-empty.

12. **`test_non_intent_agents_have_empty_descriptors`** — For RedTeamAgent, CorruptedFileReaderAgent, SystemHeartbeatAgent, assert `intent_descriptors` is empty.

13. **`test_descriptor_names_match_handle_intent`** — For each agent with descriptors, assert every descriptor `name` corresponds to an intent the agent actually handles (i.e., the agent's `decide()` or `handle_intent()` logic recognizes that intent name).

### Decomposer integration — `tests/test_prompt_builder.py`

14. **`test_decomposer_uses_dynamic_prompt`** — Create decomposer with MockLLMClient, call `refresh_descriptors()` with current descriptors. Call `decompose("read the file at /tmp/test.txt")`. Assert a valid TaskDAG is returned (MockLLMClient regex still matches).

15. **`test_decomposer_falls_back_to_legacy`** — Create decomposer with MockLLMClient, do NOT call `refresh_descriptors()`. Call `decompose("read the file at /tmp/test.txt")`. Assert it still works (legacy prompt is used).

16. **`test_decomposer_refresh_adds_new_intent`** — Start with default descriptors. Add a custom descriptor via `refresh_descriptors()`. Assert the system prompt now includes the new intent name.

### Runtime integration — `tests/test_runtime_discovery.py`

17. **`test_runtime_collects_descriptors_at_boot`** — Start runtime. Assert `decomposer._intent_descriptors` is non-empty and contains "read_file", "write_file", "run_command", etc.

18. **`test_runtime_descriptors_deduplicated`** — Multiple agents in the same pool share the same descriptors. Assert `_collect_intent_descriptors()` returns each intent name only once.

19. **`test_register_agent_type_refreshes_decomposer`** — Create a new agent class with `intent_descriptors = [IntentDescriptor(name="custom_greeting", ...)]`. Call `runtime.register_agent_type("custom", CustomAgent)`. Assert the decomposer's `_intent_descriptors` now includes "custom_greeting".

20. **`test_existing_nl_processing_unchanged`** — Start runtime with dynamic discovery. Process "read the file at /tmp/test.txt" via `process_natural_language()`. Assert it returns results (full pipeline still works).

### Milestone test — `tests/test_runtime_discovery.py`

21. **`test_dynamic_discovery_end_to_end`** — Create a minimal `TestCustomAgent(BaseAgent)` with `intent_descriptors = [IntentDescriptor(name="custom_greeting", params={"name": "..."}, description="Generate a greeting")]`. Register via `runtime.register_agent_type()`. Assert the decomposer's system prompt contains "custom_greeting" without anyone manually editing `SYSTEM_PROMPT`.

**Total: 21 new tests. Target: 477/477 (456 existing + 21 new).**

---

## Rules

1. The dynamically built prompt MUST produce identical decomposition results for all existing test cases. Backward compatibility is non-negotiable. All 456 existing tests must pass unchanged.
2. Keep `REFLECT_PROMPT` unchanged — it doesn't depend on intents.
3. Keep the existing `SYSTEM_PROMPT` in the file as `_LEGACY_SYSTEM_PROMPT` and mark it as deprecated. It's used as fallback when no descriptors are provided.
4. `IntentDescriptor` is declared on the **class**, not the instance. It's part of the agent type definition, not per-agent state.
5. The PromptBuilder must be deterministic — same descriptors in → same prompt out. Sort descriptors by name for stability.
6. Do NOT modify `MockLLMClient` patterns for existing intents — those must continue working unchanged.
7. `register_agent_type()` is a new method on `ProbOSRuntime`. It delegates to `spawner.register()` and then refreshes the decomposer's descriptors.
8. Run `uv run pytest tests/ -v` after every file change to catch regressions early.
9. Update `PROGRESS.md` when done: add Phase 6b section, new AD entries, update test counts, update "What's Next".
