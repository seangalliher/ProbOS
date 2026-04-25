# AD-311/312: Architect Deep Localize + CodebaseIndex Structured Tools

*"A First Officer who reads the schematics before presenting them to the Captain."*

The ArchitectAgent (AD-306/310) produces proposals, but its single-pass `perceive()` only reads the first 80 lines of 5 keyword-matched files. This is why it hallucinated `Registry.get_registered_agents()` (doesn't exist — the real method is `registry.all()`) and missed the shell→panels rendering pattern entirely when asked to design a `/agents` command.

Claude Code and Codex don't work this way. They iteratively explore: read a file, follow a reference, read another file, verify an API exists, find callers, check tests. This prompt brings the same capability to the Architect through two complementary changes:

1. **AD-311:** Replace the single-pass Layer 2 with a 3-step "localize → inspect → verify" pipeline using two additional LLM calls (fast tier) before the main deep-tier proposal call.
2. **AD-312:** Add structured query methods to CodebaseIndex that the Architect calls during localization — `find_callers()`, `find_tests_for()`, `get_full_api_surface()`.

Inspired by the Agentless paper (Xia et al., 2024) — a 2-phase localize-then-repair pipeline that matches full agentic systems on SWE-bench.

**Current AD count:** AD-310. This prompt uses AD-311 and AD-312.
**Current test count:** 1838 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files completely before writing any code:

1. `src/probos/cognitive/architect.py` — full file (454 lines). Pay close attention to:
   - `perceive()` method (lines 171-329) — the 7 context layers you're modifying
   - `instructions` system prompt (lines 72-161) — you'll add verification rule #6
   - `_build_user_message()` (lines 331-348) — unchanged but understand the flow
   - `_parse_proposal()` (lines 392-453) — unchanged but understand the output format
2. `src/probos/cognitive/codebase_index.py` — full file (~370 lines). Understand:
   - `query()` (line 126) — returns `matching_files`, `matching_agents`, `matching_methods`, `layer`
   - `_api_surface` dict (line 81) — `class_name → list[{method, signature, line}]`
   - `_KEY_CLASSES` (line 45) — which classes get their API surface extracted
   - `_file_tree` dict (line 77) — `rel_path → {path, docstring, classes}`
   - `read_source()` (line 211) — bounded file reading
   - `_analyze_file()` (line 311) — AST-based metadata extraction
3. `src/probos/cognitive/cognitive_agent.py` — lines 79-128. Understand the `decide()` pipeline:
   - `perceive()` → `decide()` → `act()` is the CognitiveAgent lifecycle
   - `decide()` calls `_build_user_message(observation)` and passes it to the LLM
   - Only one LLM call happens in `decide()`. The Architect's new localization calls happen in `perceive()`, before `decide()`.
4. `src/probos/substrate/registry.py` — full file (79 lines). The AgentRegistry API surface — this is the class the Architect hallucinated a method for.
5. `tests/test_architect.py` — existing test patterns for the ArchitectAgent.
6. `tests/test_codebase_index.py` — existing test patterns for CodebaseIndex.

---

## What To Build

### Step 1: CodebaseIndex Structured Query Methods (AD-312)

**File:** `src/probos/cognitive/codebase_index.py` (existing)

Add these methods to the `CodebaseIndex` class after the existing `read_doc_sections()` method (after line 305):

**1a. `find_callers(method_name: str, max_results: int = 10) -> list[dict]`**

Search all indexed source files for references to a method name. Use simple text search (not AST) for speed:
```python
def find_callers(self, method_name: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Find files that reference a method name (text search across indexed sources)."""
```
- Iterate over `self._file_tree` (skip `docs:` entries)
- For each file, call `self.read_source(rel_path)` and check if `method_name` appears in the text
- For each match, collect `{"path": rel, "lines": [line_numbers_where_found]}`
- Return up to `max_results`, sorted by number of matches descending
- Cache results in a `_caller_cache: dict[str, list[dict]]` to avoid re-scanning

**1b. `find_tests_for(file_path: str) -> list[str]`**

Given a source file path, find its test files using naming conventions:
```python
def find_tests_for(self, file_path: str) -> list[str]:
    """Find test files for a given source file using naming conventions."""
```
- Extract the module name from the path (e.g., `experience/panels.py` → `panels`, `substrate/registry.py` → `registry`)
- Search `self._file_tree` for files matching:
  - `test_{module}.py` pattern in the path
  - Files whose path contains both `test` and the module name
- Also search for files that import from the module (check docstring/class metadata)
- Return list of matching relative paths

**1c. `get_full_api_surface() -> dict[str, list[dict]]`**

Return the complete `_api_surface` dict (already built at startup):
```python
def get_full_api_surface(self) -> dict[str, list[dict[str, str]]]:
    """Return public API surface for all key classes."""
    return dict(self._api_surface)
```

**1d. Expand `_KEY_CLASSES`**

Add these classes to `_KEY_CLASSES` (line 45) so their API surfaces are extracted at build time:
```python
_KEY_CLASSES = {
    "ProbOSRuntime",
    "TrustNetwork",
    "IntentBus",
    "HebbianRouter",
    "DreamingEngine",
    "ResourcePool",
    "PoolScaler",
    "AgentRegistry",
    "EscalationManager",
    "AttentionManager",
    "CodebaseIndex",       # ADD — so Architect can see its own tools
    "PoolGroupRegistry",   # ADD — pool group queries
    "Shell",               # ADD — slash command dispatch pattern
}
```

### Step 2: Architect 3-Step Localize Pipeline (AD-311)

**File:** `src/probos/cognitive/architect.py` (existing)

**2a. Replace Layer 2 in `perceive()`**

Replace the current Layer 2 (lines 199-215) with a 3-step localization pipeline. The key insight: use two cheap fast-tier LLM calls *during perceive()* to narrow down which files to read deeply, before the main deep-tier proposal call in `decide()`.

The Architect already has access to `self._llm_client` (inherited from CognitiveAgent). Use it for the localization calls.

**Step 1 — File Selection (fast tier):**
```python
# Layer 2a: LLM-guided file selection
query_results = codebase_index.query(feature)
all_files = query_results.get("matching_files", [])[:20]
# Also add matching_methods to help the LLM
matching_methods = query_results.get("matching_methods", [])

# Build a concise file list for the LLM
file_list = "\n".join(
    f"  {f['path']} — {f.get('docstring', 'no description')}"
    for f in all_files
)
method_list = "\n".join(
    f"  {m['class']}.{m['method']}() in {m.get('file', '?')}"
    for m in matching_methods[:15]
)

selection_prompt = (
    f"Feature request: {feature}\n\n"
    f"## Candidate files (keyword matches)\n{file_list}\n\n"
    f"## Candidate methods\n{method_list}\n\n"
    "Which files (up to 8) are most relevant to implementing this feature? "
    "Include files that would need to be MODIFIED, files with PATTERNS to follow, "
    "and TEST files that would need updating.\n\n"
    "Reply with one file path per line, nothing else."
)

selection_request = LLMRequest(
    prompt=selection_prompt,
    system_prompt="You are a code reviewer selecting relevant files for a feature implementation.",
    tier="fast",
)
selection_response = await self._llm_client.complete(selection_request)
```

Parse the response to extract file paths. Filter against known paths in the file tree. Fall back to the top 5 keyword matches if the LLM response is unparseable.

**Step 2 — Deep Read (no LLM, just read full source):**

For each selected file (up to 8), read the **full source** (not first 80 lines):
```python
# Layer 2b: Full source of selected files
for path in selected_paths:
    source = codebase_index.read_source(path)  # full file, no line limits
    # ... format into context
```

Budget: cap total source at 4000 lines across all files. If a single file exceeds 500 lines, include only the first 500 lines but note "truncated at 500 lines" in the context.

**Step 3 — API Verification + Caller/Test Discovery (fast tier):**
```python
# Layer 2c: Structured queries
for path in selected_paths:
    # Find test files
    tests = codebase_index.find_tests_for(path)
    # ... include test file headers in context

    # Find callers of key methods in selected files
    for cls_methods in codebase_index.get_api_surface(cls_name):
        callers = codebase_index.find_callers(method_name)
        # ... include caller info in context

# Include full API surface for verification
api_surface = codebase_index.get_full_api_surface()
api_section = ["## API Surface (verified method signatures)"]
for cls, methods in sorted(api_surface.items()):
    api_section.append(f"\n### {cls}")
    for m in methods:
        api_section.append(f"  {m['method']}({m.get('signature', '')})")
context_parts.append("\n".join(api_section))
```

**2b. Add verification instruction**

Add rule #6 to the `instructions` system prompt (after line 96):
```
6. For every method or function you reference in your proposal, VERIFY it exists in
   the "API Surface" section. If a method does not appear there, explicitly state
   "UNVERIFIED: <method_name> — could not confirm existence" in your RISKS section.
   Never assert a method exists unless you can see it in the API Surface or source code.
```

**2c. Update the context description in `instructions`**

Update the context listing (lines 76-84) to reflect the new capabilities:
```
You receive rich codebase context including:
- The full file tree (every file path in the project)
- LLM-selected relevant files with FULL source code (not just first 80 lines)
- Test files associated with each target file
- Caller analysis showing which files use modified methods
- Verified API surface for all key classes (method signatures)
- All existing slash commands
- All existing API routes
- The current crew structure (pool groups and pools)
- Roadmap and progress documentation
- Recent architecture decisions with AD numbers
- A sample build prompt showing the expected output quality
```

**2d. Import LLMRequest**

Add to the imports at the top of `architect.py`:
```python
from probos.types import LLMRequest
```
(Check if it's already imported — if so, skip this.)

### Step 3: Tests (AD-311/312)

**File:** `tests/test_codebase_index.py` (existing — add new tests)

Add test class `TestStructuredQueries`:
```python
class TestStructuredQueries:
    """Tests for AD-312 structured query methods."""

    def test_find_callers_returns_matches(self, codebase_index):
        """find_callers() finds files referencing a method."""

    def test_find_callers_empty(self, codebase_index):
        """find_callers() returns [] for nonexistent method."""

    def test_find_callers_caches(self, codebase_index):
        """Second call uses cache (no re-scan)."""

    def test_find_tests_for_panels(self, codebase_index):
        """find_tests_for('experience/panels.py') finds test_experience.py."""

    def test_find_tests_for_unknown(self, codebase_index):
        """find_tests_for() returns [] for unknown file."""

    def test_get_full_api_surface(self, codebase_index):
        """get_full_api_surface() returns dict with key classes."""

    def test_expanded_key_classes(self, codebase_index):
        """API surface includes CodebaseIndex, PoolGroupRegistry, Shell."""
```

**File:** `tests/test_architect.py` (existing — add new tests)

Add test class `TestDeepLocalize`:
```python
class TestDeepLocalize:
    """Tests for AD-311 three-step localize pipeline."""

    @pytest.mark.asyncio
    async def test_perceive_reads_full_source(self, architect_agent):
        """Layer 2b reads full file source, not first 80 lines."""

    @pytest.mark.asyncio
    async def test_perceive_includes_api_surface(self, architect_agent):
        """Context includes API Surface section with method signatures."""

    @pytest.mark.asyncio
    async def test_perceive_includes_test_files(self, architect_agent):
        """Context includes discovered test file paths."""

    @pytest.mark.asyncio
    async def test_perceive_includes_callers(self, architect_agent):
        """Context includes caller analysis for relevant methods."""

    @pytest.mark.asyncio
    async def test_perceive_falls_back_on_llm_failure(self, architect_agent):
        """If fast-tier selection fails, falls back to keyword top-5."""

    @pytest.mark.asyncio
    async def test_perceive_caps_source_at_budget(self, architect_agent):
        """Total source lines capped at 4000 across all files."""

    def test_instructions_have_rule_6(self):
        """System prompt includes API verification rule."""
        from probos.cognitive.architect import ArchitectAgent
        assert "UNVERIFIED" in ArchitectAgent.instructions

    def test_instructions_describe_full_source(self):
        """System prompt mentions full source code, not first 80 lines."""
        from probos.cognitive.architect import ArchitectAgent
        assert "FULL source" in ArchitectAgent.instructions or "full source" in ArchitectAgent.instructions
```

Use the existing test fixtures (`architect_agent`, `codebase_index`) — check `conftest.py` and existing tests for the exact fixture names and patterns. Mock `self._llm_client.complete()` for the fast-tier calls to return controlled file selections.

---

## Architecture Diagram

```
Before (AD-310):
  perceive()
    Layer 2: query(feature) → top 5 files → read first 80 lines each
  decide()
    _build_user_message() → one deep-tier LLM call → proposal

After (AD-311/312):
  perceive()
    Layer 2a: query(feature) → 20 candidates + methods
             → fast-tier LLM selects 8 most relevant files
    Layer 2b: read FULL source of 8 selected files (≤4000 lines total)
    Layer 2c: find_tests_for() each file → include test paths + headers
             find_callers() for key methods → include caller paths
             get_full_api_surface() → include verified method signatures
  decide()
    _build_user_message() → one deep-tier LLM call → proposal
                            (now with 10x more context and verified APIs)
```

Total LLM calls per design request: 1 fast + 1 deep (was: 1 deep).
Additional latency: ~1-2 seconds for the fast-tier selection call.
Context quality: full source of 8 files + test discovery + caller graph + verified API surface vs 80 lines of 5 files with unverified APIs.

---

## Do NOT Build

- Do NOT modify the `_parse_proposal()` method — output format stays the same
- Do NOT modify the `act()` method — post-processing stays the same
- Do NOT modify `_build_user_message()` — it already passes `codebase_context` through
- Do NOT add embedding-based search — that's a future enhancement
- Do NOT modify `decide()` in CognitiveAgent — the fast-tier calls go in `perceive()`
- Do NOT modify Layers 1, 3, 4, 5, 6, or 7 in `perceive()` — only Layer 2 changes
- Do NOT modify any Builder code — that's AD-313+
- Do NOT break the existing test suite — all 1838 pytest + 21 vitest must still pass

---

## Verification

1. `uv run pytest tests/test_codebase_index.py -v` — new structured query tests pass
2. `uv run pytest tests/test_architect.py -v` — new deep localize tests + existing tests pass
3. `uv run pytest tests/ -x -q` — full suite green
4. Manual smoke test: `uv run probos serve` → `/design Add a /agents slash command that lists all registered agent types with their tier, team, and pool size` → verify the proposal now:
   - References `panels.py` (not just `shell.py`)
   - References `render_agent_table()` as the existing pattern to follow
   - References correct API methods (`registry.all()`, `registry.get_by_pool()`, not `get_registered_agents()`)
   - Identifies test files (`test_experience.py`, `test_agent_tiers.py`)
   - Includes method signatures in the proposal description
