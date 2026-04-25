# AD-320: Introspection Delegation — Grounded Self-Knowledge Answers

## Context

AD-317 added grounding rules ("only describe listed capabilities"). AD-318 added `SystemSelfModel` — structured, always-current topology and health data. AD-319 added `_verify_response()` — post-hoc confabulation detection. These layers have progressively improved accuracy, but a fundamental gap remains:

**The LLM still generates self-knowledge answers from training data, then we check them afterward.** The Decomposer either answers directly in the `response` field (limited to 500 chars of SYSTEM CONTEXT) or routes to the IntrospectionAgent, which returns raw data that `reflect()` synthesizes — but the reflect LLM has no grounding rules and can confabulate department names, agent counts, etc.

**AD-320 inverts this: provide the grounded facts FIRST, so the LLM synthesizes from verified data instead of inventing details.** Level 4 of the self-knowledge grounding progression: rules (AD-317) → data (AD-318) → verification (AD-319) → **delegation** (AD-320).

The IntrospectionAgent (`src/probos/agents/introspect.py`) already handles 11 intents including `agent_info`, `team_info`, `system_health`, and `introspect_system`. The problem isn't missing intents — it's that the agent returns raw dicts, and the reflect step confabulates when synthesizing. AD-320 enriches the IntrospectionAgent's self-knowledge handlers to return grounded, pre-formatted text that the reflector can trust.

## What to Build

### Part 1: Add `_grounded_context()` helper to IntrospectionAgent

Add a new private method to `IntrospectionAgent` in `src/probos/agents/introspect.py`:

```python
def _grounded_context(self) -> str:
    """Build grounded self-knowledge context from SystemSelfModel (AD-320).

    Returns a detailed text block of verified runtime facts for use as
    grounding material in introspection responses. More detailed than
    SystemSelfModel.to_context() — includes per-pool breakdowns with
    department associations and full intent listing.
    """
    rt = self._runtime
    if not rt:
        return ""

    try:
        model = rt._build_system_self_model()
    except Exception:
        return ""

    parts: list[str] = []

    # Identity + health
    parts.append(f"System: ProbOS | Mode: {model.system_mode}")
    if model.uptime_seconds > 0:
        mins = int(model.uptime_seconds // 60)
        parts.append(f"Uptime: {mins} minutes")

    # Topology summary
    parts.append(f"Total pools: {model.pool_count}")
    parts.append(f"Total agents: {model.agent_count}")
    parts.append(f"Registered intents: {model.intent_count}")

    # Departments with their pools
    if model.departments:
        parts.append(f"\nDepartments: {', '.join(model.departments)}")
    if model.pools:
        # Group pools by department
        dept_pools: dict[str, list] = {}
        ungrouped: list = []
        for p in model.pools:
            if p.department:
                dept_pools.setdefault(p.department, []).append(p)
            else:
                ungrouped.append(p)
        for dept_name, pools in sorted(dept_pools.items()):
            pool_items = ", ".join(
                f"{p.name} ({p.agent_type}, {p.agent_count} agents)"
                for p in pools
            )
            parts.append(f"  {dept_name}: {pool_items}")
        if ungrouped:
            pool_items = ", ".join(
                f"{p.name} ({p.agent_type}, {p.agent_count} agents)"
                for p in ungrouped
            )
            parts.append(f"  Unassigned: {pool_items}")

    # Intent listing
    try:
        descriptors = rt.decomposer._intent_descriptors
        if descriptors:
            intent_names = sorted(d.name for d in descriptors)
            parts.append(f"\nAvailable intents: {', '.join(intent_names)}")
    except Exception:
        pass

    # Health signals
    if model.recent_errors:
        parts.append(f"\nRecent errors: {'; '.join(model.recent_errors)}")
    if model.last_capability_gap:
        parts.append(f"Last capability gap: {model.last_capability_gap}")

    return "\n".join(parts)
```

### Part 2: Enrich `_agent_info()` with grounded context

In `src/probos/agents/introspect.py`, find the `_agent_info()` method (around line 190). Currently it returns raw registry data. Modify it to **append grounded context** to its output.

At the end of the `_agent_info()` method, just before the final `return IntentResult(...)`, add grounded context to the output value. The output is a dict — add a `"grounded_context"` key:

```python
# Append grounded topology for reflector (AD-320)
grounded = self._grounded_context()
if grounded:
    output["grounded_context"] = grounded
```

Where `output` is the dict being returned as the IntentResult's `output` (it may be named differently — check the actual variable name). The pattern is: find where the IntentResult is constructed, and add the grounded context to its output dict.

### Part 3: Enrich `_system_health()` with grounded context

Find the `_system_health()` method (handles the `system_health` intent). Same pattern — add `"grounded_context"` to the output dict before returning.

### Part 4: Enrich `_team_info()` with grounded context

Find the `_team_info()` method (handles the `team_info` intent). Same pattern.

### Part 5: Enrich `_introspect_system()` with grounded context

Find the `_introspect_system()` method (handles the `introspect_system` intent). Same pattern.

### Part 6: Update the Reflect prompt to use grounded context

In `src/probos/cognitive/decomposer.py`, update `REFLECT_PROMPT` (line 197) to add a grounding rule. Add this as rule 7 (after existing rule 6):

```
7. If results include a "grounded_context" field, treat it as VERIFIED SYSTEM FACTS. \
Use these facts for any claims about pools, agents, departments, capabilities, or system state. \
Never contradict grounded_context with information from your training data.
```

### Part 7: Update `_summarize_node_result()` to preserve grounded context

In `src/probos/cognitive/decomposer.py`, find the `_summarize_node_result()` function (it's a module-level helper that summarizes node results for the reflect prompt). It currently handles `doc_snippets` specially to prevent truncation (from AD-301).

Add similar handling for `grounded_context`: if the node result's output dict contains `"grounded_context"`, extract it and append it separately, outside the truncation boundary. Follow the exact same pattern used for `doc_snippets`.

Find where `doc_snippets` is extracted. It should look something like:
```python
doc_snippets = ...
if doc_snippets:
    # append after main summary
```

Add analogous handling:
```python
# Preserve grounded context for reflector (AD-320)
grounded = ""
if isinstance(result, dict):
    output = result.get("output", result)
    if isinstance(output, dict):
        grounded = output.get("grounded_context", "")

# ... after main summary is built ...
if grounded:
    summary += f"\n\nGROUNDED SYSTEM FACTS:\n{grounded}"
```

The exact implementation depends on the current structure of `_summarize_node_result()`. The goal is: when grounded_context is present, it appears verbatim in the reflect prompt, clearly labeled, not truncated.

### Part 8: Tests

Add tests to `tests/test_decomposer.py` in a new test class section after `TestPreResponseVerification`.

**Test class: `TestIntrospectionDelegation` (AD-320)**

1. **`test_grounded_context_includes_topology`** — Create a mock runtime with 2 pools (filesystem: 3 agents, shell: 2 agents), 1 pool group ("Engineering"), `_build_system_self_model()` returning a populated `SystemSelfModel`. Create an `IntrospectionAgent` with that runtime. Call `_grounded_context()`. Verify output contains: `"Total pools: 2"`, `"Total agents: 5"`, `"Engineering"`, `"filesystem"`, `"shell"`.

2. **`test_grounded_context_includes_departments`** — Same mock with 2 pool groups. Verify both department names appear in grounded context.

3. **`test_grounded_context_includes_intents`** — Mock runtime with `decomposer._intent_descriptors` containing 3 IntentDescriptor objects. Verify `"Available intents:"` appears and all 3 intent names are listed.

4. **`test_grounded_context_includes_health`** — Mock runtime with `_recent_errors=["timeout"]` and `_last_capability_gap="deploy app"` on the SystemSelfModel. Verify output contains `"Recent errors"` and `"capability gap"`.

5. **`test_grounded_context_no_runtime_returns_empty`** — Create agent with `_runtime=None`. Verify `_grounded_context()` returns `""`.

6. **`test_grounded_context_groups_pools_by_department`** — Mock 3 pools across 2 departments. Verify each department heading contains only its pools.

7. **`test_reflect_prompt_has_grounded_context_rule`** — Import `REFLECT_PROMPT` from `probos.cognitive.decomposer`. Verify it contains `"grounded_context"` and `"VERIFIED SYSTEM FACTS"`.

8. **`test_summarize_preserves_grounded_context`** — Import `_summarize_node_result` from `probos.cognitive.decomposer`. Pass a result dict with `{"output": {"data": "...", "grounded_context": "Total pools: 14\nTotal agents: 54"}}`. Verify the returned summary contains `"GROUNDED SYSTEM FACTS"` and `"Total pools: 14"`.

9. **`test_summarize_without_grounded_context_unchanged`** — Same function, pass result without `grounded_context`. Verify `"GROUNDED SYSTEM FACTS"` does NOT appear.

Also add tests in `tests/test_decomposer.py` or a new test file section if space is tight:

10. **`test_agent_info_includes_grounded_context`** — Create IntrospectionAgent with mock runtime. Call `handle_intent()` with an `agent_info` IntentMessage (empty params). Verify the result output dict contains `"grounded_context"` key with non-empty string.

11. **`test_system_health_includes_grounded_context`** — Same pattern with `system_health` intent.

12. **`test_team_info_includes_grounded_context`** — Same pattern with `team_info` intent.

### Tracking Updates

Update these files:
- `PROGRESS.md` line 3: Change `Phase 32r` to `Phase 32s`, update test count
- `DECISIONS.md`: Add `## Phase 32s: Introspection Delegation (AD-320)` section with status and implementation summary

## Anti-Scope — Do NOT

- Do NOT create a new agent class. The IntrospectionAgent already exists with the right intents. Enrich it, don't replace it.
- Do NOT create new intents. The existing `agent_info`, `team_info`, `system_health`, and `introspect_system` intents cover self-knowledge questions. The problem is the quality of their responses, not missing intent coverage.
- Do NOT modify `self_model.py`. The `SystemSelfModel` data structure is complete from AD-318.
- Do NOT modify `prompt_builder.py` or the PROMPT_PREAMBLE. The grounding rules are fine. The fix is in the reflect pipeline.
- Do NOT modify `_verify_response()` (AD-319). Verification stays as a backstop; delegation is the primary fix.
- Do NOT add LLM calls to the IntrospectionAgent. It stays as a non-LLM agent. The grounded context gives the reflect LLM better material to work with.
- Do NOT modify pool registration or pool group assignments. The IntrospectionAgent stays in the "introspect" pool in the "core" PoolGroup.
- Do NOT modify `runtime.py` beyond what's needed for the tests.
