# AD-316a: Architect Proposal Validation + Pattern Recipes

## Context

The ArchitectAgent (`src/probos/cognitive/architect.py`) generates ArchitectProposal objects from LLM output. Currently, `act()` (line 513) performs **zero programmatic validation** — whatever the LLM produces in the `===PROPOSAL===` block is blindly forwarded. Additionally, the `instructions` string (line 72) contains good process guidance but no reusable **pattern recipes** for common change types, forcing the LLM to figure out file patterns from scratch each time.

## What to Build

### Part 1: `_validate_proposal()` method (new, called from `act()`)

Add a private `_validate_proposal(proposal: ArchitectProposal) -> list[str]` method that returns a list of warning strings. Empty list = valid.

**Validation rules:**

1. **Non-empty required fields** — `proposal.title`, `proposal.summary`, `proposal.build_spec.description` must be non-empty strings (after `.strip()`). Warning: `"Missing required field: {field}"`

2. **Non-empty TEST_FILES** — `proposal.build_spec.test_files` must have at least one entry. Warning: `"No test files specified — every change needs tests"`

3. **TARGET_FILES exist in file tree** — For each path in `proposal.build_spec.target_files`, check if it exists in `codebase_index._file_tree.keys()` OR follows an existing directory pattern (the directory portion of the path exists as a prefix of at least one known file). Access codebase_index via `self._runtime.codebase_index` (same pattern as `perceive()` at lines 198-200). If no runtime or no codebase_index, skip this check. Warning: `"TARGET_FILE not found and no matching directory: {path}"`

4. **REFERENCE_FILES exist in file tree** — Same check for `proposal.build_spec.reference_files`. Warning: `"REFERENCE_FILE not found: {path}"`

5. **Valid priority** — `proposal.priority` must be one of `{"high", "medium", "low"}`. Warning: `"Invalid priority '{val}', expected high/medium/low"`

6. **Description minimum length** — `proposal.build_spec.description` must be at least 100 characters. Warning: `"Description too short ({n} chars) — Builder needs detailed specifications"`

**Integration in `act()`:**

After the `_parse_proposal()` call succeeds (line 519), call `_validate_proposal(proposal)`. If warnings are returned:
- Still return `success: True` (warnings are advisory, not blocking)
- Add a `"warnings": warnings` key to the result dict alongside `"proposal"`

This is intentionally non-blocking. The Captain sees warnings in the HXI approval UI and can choose to reject or approve anyway.

### Part 2: Pattern Recipes (appended to `instructions` string)

Add a `PATTERN RECIPES` section at the end of the `instructions` string (before the closing `"""`), after the `IMPORTANT RULES` section (line 173). This gives the LLM reusable templates for the 3 most common change types.

Add this exact text:

```
PATTERN RECIPES:
When your feature matches one of these common patterns, use the recipe as a starting
point. Verify all paths against your File Tree — these are templates, not guarantees.

Recipe: NEW AGENT
  TARGET_FILES:
  - src/probos/agents/<team>/<agent_name>.py  (or src/probos/cognitive/<name>.py for cognitive agents)
  REFERENCE_FILES:
  - src/probos/substrate/agent.py  (BaseAgent)
  - src/probos/cognitive/cognitive_agent.py  (if cognitive)
  - An existing agent in the same team as a pattern reference
  TEST_FILES:
  - tests/test_<agent_name>.py
  CHECKLIST:
  - Class inherits BaseAgent or CognitiveAgent
  - agent_type class var set
  - _handled_intents populated
  - intent_descriptors list with IntentDescriptor entries
  - Pool registration in pool config or runtime setup
  - PoolGroup assignment if applicable

Recipe: NEW SLASH COMMAND
  TARGET_FILES:
  - src/probos/experience/shell.py  (add to COMMANDS dict + handler)
  - src/probos/experience/panels.py  (if command needs TUI output)
  REFERENCE_FILES:
  - src/probos/experience/shell.py  (existing command patterns)
  - src/probos/experience/panels.py  (existing panel renderers)
  TEST_FILES:
  - tests/test_shell.py
  CHECKLIST:
  - Entry in COMMANDS dict with help text
  - Handler method on Shell class
  - Panel renderer in panels.py if needed
  - Do NOT add to api.py unless the command also needs an API endpoint

Recipe: NEW API ENDPOINT
  TARGET_FILES:
  - src/probos/api.py
  REFERENCE_FILES:
  - src/probos/api.py  (existing endpoint patterns)
  - src/probos/experience/shell.py  (if endpoint mirrors a slash command)
  TEST_FILES:
  - tests/test_builder_api.py  (or tests/test_architect_api.py — follow the pattern)
  CHECKLIST:
  - FastAPI route with type-annotated request/response models
  - WebSocket event broadcast if real-time UI update needed
  - _track_task() wrapper if background processing
  - _safe_send() for any WebSocket sends
  - Do NOT duplicate logic already in an agent — delegate to intent bus
```

### Part 3: Tests

Add tests to `tests/test_architect_agent.py` in a new test class section.

**Test class: `TestProposalValidation` (AD-316a)**

Use the existing `_make_agent()` helper (line 462) to create an agent with a mock runtime that has a `codebase_index` with known `_file_tree` keys.

Tests:

1. **`test_valid_proposal_no_warnings`** — Parse `SAMPLE_PROPOSAL`, run through `_validate_proposal()`. The target files `src/probos/security/egress.py` and `src/probos/security/policy.py` don't exist in the mock file tree, but the mock should include at least one file with `src/probos/security/` prefix so the directory pattern check passes. Verify returned warnings list is empty.

2. **`test_missing_title_warns`** — Create an ArchitectProposal with `title=""`. Verify warning contains `"Missing required field"`.

3. **`test_empty_test_files_warns`** — Create an ArchitectProposal with `build_spec.test_files=[]`. Verify warning contains `"No test files specified"`.

4. **`test_target_file_unknown_path_warns`** — Set mock `_file_tree` to `{"src/probos/mesh/routing.py": {...}}`. Create proposal with target file `"src/probos/web/routes.py"`. No file with `src/probos/web/` prefix exists. Verify warning contains `"TARGET_FILE not found"`.

5. **`test_target_file_new_in_existing_dir_ok`** — Set mock `_file_tree` to `{"src/probos/mesh/routing.py": {...}}`. Create proposal with target file `"src/probos/mesh/policy.py"`. Directory prefix `src/probos/mesh/` matches existing files. Verify no warning for this path.

6. **`test_short_description_warns`** — Create an ArchitectProposal with `build_spec.description="Too short"`. Verify warning contains `"Description too short"`.

7. **`test_invalid_priority_warns`** — Create an ArchitectProposal with `priority="critical"`. Verify warning contains `"Invalid priority"`.

8. **`test_act_includes_warnings_in_result`** — Call `act()` with a proposal that has empty test_files. Verify `result["result"]["warnings"]` is a non-empty list. Verify `result["success"]` is still `True`.

9. **`test_act_no_warnings_key_when_valid`** — Call `act()` with `SAMPLE_PROPOSAL` (modify mock to make it valid). Verify `"warnings"` is either absent or an empty list in the result.

10. **`test_validation_skipped_without_runtime`** — Create agent with no runtime. Call `_validate_proposal()`. Only non-file-tree checks should run (title, description length, priority, test_files). File path checks should be skipped gracefully.

**Test class: `TestPatternRecipes` (AD-316a)**

1. **`test_instructions_contain_pattern_recipes`** — Verify `"PATTERN RECIPES"` appears in `ArchitectAgent.instructions`.

2. **`test_recipe_new_agent`** — Verify `"Recipe: NEW AGENT"` in instructions and `"BaseAgent"` is mentioned.

3. **`test_recipe_new_slash_command`** — Verify `"Recipe: NEW SLASH COMMAND"` in instructions and `"shell.py"` is mentioned.

4. **`test_recipe_new_api_endpoint`** — Verify `"Recipe: NEW API ENDPOINT"` in instructions and `"api.py"` is mentioned.

### Tracking Updates

Update these files:
- `PROGRESS.md` line 3: Change `Phase 32o` to `Phase 32p`, update test count
- `DECISIONS.md`: Add `## Phase 32p: Architect Proposal Validation + Pattern Recipes (AD-316a)` section with status and implementation summary

## Anti-Scope — Do NOT

- Do NOT make validation blocking (return `success: False`). Warnings are advisory.
- Do NOT add any LLM calls to the validation. This is pure programmatic checking.
- Do NOT modify `_parse_proposal()`. It stays as-is.
- Do NOT modify `perceive()`. No changes to context gathering.
- Do NOT add recipe patterns beyond the 3 specified (agent, slash command, API endpoint).
- Do NOT create any new files besides tests.
