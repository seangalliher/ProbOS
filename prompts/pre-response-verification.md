# AD-319: Pre-Response Verification — Fact-Check Against SystemSelfModel

## Context

AD-317 added grounding rules to the Decomposer's system prompt ("only describe listed capabilities," "never fabricate systems"). AD-318 added `SystemSelfModel` — a structured, always-current snapshot of verified runtime facts injected into the decompose prompt as SYSTEM CONTEXT.

But the grounding rules are *advisory*. The LLM can still confabulate in two places:

1. **`dag.response`** — The direct conversational reply from `decompose()` (returned at runtime.py line 1553 in the no-nodes path). The Decomposer might claim ProbOS has pools, departments, or capabilities it doesn't actually have.
2. **`reflection`** — The synthesis produced by `reflect()` after DAG execution (stored in `execution_result["reflection"]` at runtime.py line 1606). The reflector might reference nonexistent agent types or system states.

**AD-319 adds a fast, programmatic `_verify_response()` method** that cross-references response text against the SystemSelfModel to detect and flag confabulated facts. Level 3 of the self-knowledge grounding progression: rules (AD-317) → data (AD-318) → **verification** (AD-319) → delegation (AD-320).

## Design Principle

Verification is **non-blocking** and **zero-LLM**. It's a fast string-matching pass, not a second LLM call. When violations are detected:
- Add a correction footnote to the response text (appended, not replacing the response)
- Log warnings for observability
- Never suppress or block the response

## What to Build

### Part 1: `_verify_response()` method on runtime.py

Add a new private method to the `ProbOSRuntime` class:

```python
def _verify_response(self, response_text: str, self_model: SystemSelfModel) -> str:
    """Verify response text against SystemSelfModel facts (AD-319).

    Returns the response text with a correction footnote appended
    if any confabulated facts are detected. Returns original text
    if no issues found.
    """
    if not response_text or not response_text.strip():
        return response_text

    violations: list[str] = []
    response_lower = response_text.lower()

    # Check 1: Pool count claims
    # Look for patterns like "X pools" where X is wrong
    import re
    pool_count_matches = re.findall(r'(\d+)\s+pools?\b', response_lower)
    for match in pool_count_matches:
        claimed = int(match)
        if claimed != self_model.pool_count and claimed != 0:
            violations.append(
                f"pools: claimed {claimed}, actual {self_model.pool_count}"
            )

    # Check 2: Agent count claims
    agent_count_matches = re.findall(r'(\d+)\s+agents?\b', response_lower)
    for match in agent_count_matches:
        claimed = int(match)
        if claimed != self_model.agent_count and claimed != 0:
            violations.append(
                f"agents: claimed {claimed}, actual {self_model.agent_count}"
            )

    # Check 3: Fabricated department names
    # Build set of known department names (lowercase for comparison)
    known_departments = {d.lower() for d in self_model.departments}
    # Common department-like words that the LLM might fabricate
    DEPARTMENT_PATTERNS = [
        "navigation", "tactical", "helm", "ops", "logistics",
        "research", "diplomacy", "intelligence", "weapons",
    ]
    for dept in DEPARTMENT_PATTERNS:
        if dept in response_lower and dept not in known_departments:
            # Only flag if the word appears in a department-like context
            # e.g. "the Navigation department" or "Navigation team"
            dept_context = re.search(
                rf'\b{re.escape(dept)}\b\s+(?:department|team|division|pool)',
                response_lower,
            )
            if dept_context:
                violations.append(f"unknown department: '{dept}'")

    # Check 4: Fabricated pool names
    known_pools = {p.name.lower() for p in self_model.pools}
    # Look for "the X pool" pattern with names that don't exist
    pool_ref_matches = re.findall(
        r'the\s+(\w+)\s+pool\b', response_lower
    )
    for pool_name in pool_ref_matches:
        if pool_name not in known_pools and pool_name not in {
            "agent", "worker", "thread", "connection",  # generic words
        }:
            violations.append(f"unknown pool: '{pool_name}'")

    # Check 5: System mode contradictions
    if self_model.system_mode == "active" and "system is idle" in response_lower:
        violations.append("mode: claimed idle, actual active")
    elif self_model.system_mode == "idle" and "system is active" in response_lower:
        violations.append("mode: claimed active, actual idle")
    elif self_model.system_mode == "dreaming" and (
        "system is active" in response_lower or "system is idle" in response_lower
    ):
        violations.append(f"mode: actual dreaming")

    if not violations:
        return response_text

    # Log violations
    logger.warning(
        "Response verification found %d violation(s): %s",
        len(violations),
        "; ".join(violations),
    )

    # Append correction footnote
    correction = (
        "\n\n[Note: Some details in this response may be imprecise. "
        f"Verified system state: {self_model.pool_count} pools, "
        f"{self_model.agent_count} agents, "
        f"mode {self_model.system_mode}.]"
    )
    return response_text + correction
```

Add the import for `SystemSelfModel` — it should already be imported from AD-318 (`from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel` near line 43). Verify it's there; if not, add it.

### Part 2: Wire into the two response paths in `process_natural_language()`

**Path 1: No-nodes path (line 1553)**

At runtime.py line 1549, after `"response": dag.response,` is set in the result dict, and before `return result` at line 1553, add verification:

```python
# Verify response against self-model (AD-319)
if result.get("response"):
    result["response"] = self._verify_response(
        result["response"], self_model
    )
```

Insert this between line 1552 (`result["self_mod"] = self_mod_result`) and line 1553 (`return result`). It must be OUTSIDE the `if self_mod_result:` block — the verification runs on all no-nodes responses.

**Path 2: Nodes path — after reflect in `_execute_dag()`**

In `_execute_dag()` at line 1606, after `execution_result["reflection"] = reflection`, add verification of the reflection text. But `_execute_dag` doesn't have access to `self_model` — it needs to build one or accept it as a parameter.

**Preferred approach**: Pass `self_model` into `_execute_dag()` as an optional parameter.

1. Update `_execute_dag` signature (line 1566) to accept an optional `self_model`:
   ```python
   async def _execute_dag(
       self,
       dag: TaskDAG,
       text: str,
       t_start: float,
       on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
       self_model: SystemSelfModel | None = None,
   ) -> dict[str, Any]:
   ```

2. At the call site (line 1560), pass the self_model:
   ```python
   execution_result = await self._execute_dag(
       dag, text, t_start, on_event=on_event, self_model=self_model,
   )
   ```

3. After reflection is assigned (line 1606), add:
   ```python
   if reflection and self_model:
       execution_result["reflection"] = self._verify_response(
           reflection, self_model
       )
   ```
   Place this immediately after `execution_result["reflection"] = reflection` (line 1606), before the `except asyncio.TimeoutError:` block. It should be inside the `try:` block.

4. Do the same for the two fallback paths (timeout at line 1612 and exception at line 1618) — do NOT verify those since they're canned strings, not LLM output.

### Part 3: Tests

Add tests to `tests/test_decomposer.py` in a new test class section after the existing `TestSystemSelfModel` class (after line 1034).

**Test class: `TestPreResponseVerification` (AD-319)**

All tests should import and use `ProbOSRuntime._verify_response` with a mock runtime (same pattern as `TestSystemSelfModel` tests).

Helper: Create a `_make_model()` helper function inside the test class that returns a typical `SystemSelfModel` for testing:
```python
@staticmethod
def _make_model() -> SystemSelfModel:
    return SystemSelfModel(
        pool_count=14,
        agent_count=54,
        pools=[
            PoolSnapshot(name="filesystem", agent_type="file_reader", agent_count=3, department="Engineering"),
            PoolSnapshot(name="shell", agent_type="shell", agent_count=2, department="Engineering"),
            PoolSnapshot(name="medical", agent_type="vitals_monitor", agent_count=1, department="Medical"),
        ],
        departments=["Engineering", "Medical", "Science"],
        intent_count=38,
        system_mode="active",
        uptime_seconds=3600,
    )
```

Tests:

1. **`test_clean_response_unchanged`** — Pass a response with no verifiable claims (e.g. `"Hello, Captain. How may I assist you?"`). Verify returned text equals the input exactly.

2. **`test_empty_response_unchanged`** — Pass `""` and `None` (guard check). Verify returned as-is.

3. **`test_wrong_pool_count_flagged`** — Pass `"I currently manage 25 pools across the system."`. Model has `pool_count=14`. Verify returned text contains `"[Note:"` and `"14 pools"`.

4. **`test_correct_pool_count_not_flagged`** — Pass `"I currently manage 14 pools."`. Model has `pool_count=14`. Verify no `"[Note:"` in result.

5. **`test_wrong_agent_count_flagged`** — Pass `"There are 200 agents deployed."`. Model has `agent_count=54`. Verify `"[Note:"` appears and `"54 agents"` in correction.

6. **`test_fabricated_department_flagged`** — Pass `"The Navigation department handles routing."`. Model departments are `["Engineering", "Medical", "Science"]`. Verify `"[Note:"` appears.

7. **`test_known_department_not_flagged`** — Pass `"The Engineering department handles file operations."`. Verify no `"[Note:"`.

8. **`test_fabricated_pool_flagged`** — Pass `"Data is routed through the warpcore pool for processing."`. Model pools don't include "warpcore". Verify `"[Note:"` appears.

9. **`test_known_pool_not_flagged`** — Pass `"The filesystem pool handles file reads."`. Model has a pool named "filesystem". Verify no `"[Note:"`.

10. **`test_mode_contradiction_flagged`** — Pass `"The system is idle right now."`. Model has `system_mode="active"`. Verify `"[Note:"` and `"mode active"`.

11. **`test_mode_correct_not_flagged`** — Pass `"The system is active."`. Model has `system_mode="active"`. Verify no `"[Note:"`.

12. **`test_multiple_violations_all_reported`** — Pass `"I have 99 pools and 500 agents. The Navigation department is online."`. Verify `"[Note:"` appears and correction mentions `"14 pools"` and `"54 agents"`.

13. **`test_verification_logs_warning`** — Use `caplog` or mock `logger.warning`. Pass a response with wrong pool count. Verify a warning was logged containing `"violation"`.

14. **`test_generic_pool_word_not_flagged`** — Pass `"The agent pool is doing well."`. The word "agent" in "the agent pool" should be in the exclusion set and not flagged. Verify no `"[Note:"`.

### Tracking Updates

Update these files:
- `PROGRESS.md` line 3: Change `Phase 32q` to `Phase 32r`, update test count
- `DECISIONS.md`: Add `## Phase 32r: Pre-Response Verification (AD-319)` section with status and implementation summary

## Anti-Scope — Do NOT

- Do NOT add any LLM calls to verification. This is pure string matching + regex.
- Do NOT block or suppress responses. Verification only appends a footnote.
- Do NOT modify `decomposer.py`. Verification happens in `runtime.py` after the Decomposer returns.
- Do NOT modify `prompt_builder.py`. The grounding rules already exist from AD-317.
- Do NOT modify `self_model.py`. The SystemSelfModel data structure is complete from AD-318.
- Do NOT modify `response_formatter.py`. Verification happens before formatting.
- Do NOT verify timeout/error fallback strings — only verify LLM-generated text.
- Do NOT create any files besides test additions.
