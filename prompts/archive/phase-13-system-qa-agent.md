# Phase 13: SystemQAAgent — The System Tests Itself

**Goal:** After every successful self-modification (agent design or skill addition), ProbOS automatically smoke-tests the newly created agent with synthetic intents, verifies the output shape and content, records pass/fail outcomes in episodic memory, and updates the trust network accordingly. If a designed agent fails smoke tests, it is flagged for demotion or redesign — the system catches its own mistakes before the user encounters them.

This fulfils the original ProbOS vision:

> *"Shadow deployment → Comparative evaluation → Knowledge impact assessment → Cutover or rollback"*

And directly addresses the operational gap identified in AD-150 through AD-152: manual testing caught bugs that the system should have caught itself. The existing `pytest -m live_llm` integration tests validate external-facing behavior; the SystemQAAgent validates internal self-modification outcomes as they happen.

---

## Context

Right now, after `SelfModificationPipeline.handle_unhandled_intent()` succeeds:
1. The `SandboxRunner` tests the generated code with a single synthetic intent in an isolated context
2. If the sandbox passes, the agent is registered, pooled, and given probationary trust (E[trust] = 0.25)
3. The system immediately retries decomposition, routing the original user request to the new agent
4. **No further validation occurs.** If the agent produces malformed output, returns wrong data, or fails on edge cases, the user discovers it — not the system.

The existing safety infrastructure handles ongoing trust (Hebbian routing deprioritizes failing agents, trust-aware scale-down removes them), but there is no proactive smoke test at creation time beyond the single sandbox call.

ProbOS has 820 tests and automated regression coverage (AD-152), but these are developer-time checks. The system itself has no ability to test its own modifications.

---

## Design Principles

1. **Smoke, not exhaustive.** The SystemQAAgent runs 3–5 synthetic intents per new agent. It verifies output shape (correct `IntentResult` fields), basic content sanity, and error handling. It does NOT attempt full integration testing — that's what the existing trust network, Hebbian routing, and episodic memory handle over time.

2. **Non-blocking.** Smoke tests run after the self-mod pipeline succeeds and after the original user request is retried. The user gets their answer first; QA runs in the background. If QA fails, the agent is flagged but not immediately removed (the trust network handles gradual demotion).

3. **Trust-integrated.** Each smoke test outcome feeds into `trust_network.record_outcome()`. A designed agent that passes 5/5 smoke tests starts climbing from E[trust] = 0.25 toward the system default. One that fails 4/5 drops further, making Hebbian routing and scale-down remove it naturally.

4. **Episodic memory.** Smoke test results are recorded as episodes, giving the decomposer historical context ("the last time we designed a weather agent, it failed smoke tests because it didn't handle timeout errors").

5. **Event-driven.** The QA process is triggered by a `self_mod_complete` event, not by polling. It uses the existing event infrastructure.

6. **Fully test-covered.** Every deliverable in this phase has corresponding automated tests. No manual testing required. All new tests run in the standard `uv run pytest tests/ -v` suite. The phase is not complete until every new code path has at least one test exercising it.

---

## ⚠ AD Numbering: Start at AD-153

AD-146 through AD-152 exist from recent fixes. All architectural decisions in this phase start at **AD-153**. Pre-assigned numbers:

| AD | Decision |
|----|----------|
| AD-153 | Single-agent QA pool (intentional exception to Design Principle #1 — see Architectural Notes) |
| AD-154 | Non-blocking QA via `asyncio.create_task` with error containment (try/except in task body, failures logged to event log, never propagated) |
| AD-155 | Trust weight asymmetry: penalty weight (default 2.0) > reward weight (default 1.0), using existing `weight` parameter on `record_outcome()` |
| AD-156 | Param type inference from key name heuristics (not from description string parsing) |
| AD-157 | In-memory QA report store on runtime (`_qa_reports: dict[str, QAReport]`) as primary query path for `/qa` command; episodic memory as durable record |
| AD-158 | QA pool excluded from user-facing routing: `smoke_test_agent` descriptor excluded from decomposer, pool excluded from scaler |

---

## ⚠ Pre-Build Audit: Examine These Files First

Before writing any code, read the following to understand the interfaces you'll integrate with:

1. `src/probos/cognitive/self_mod.py` — `SelfModificationPipeline`, `DesignedAgentRecord`, `AgentDesigner`, `SandboxRunner`, `SandboxResult`
2. `src/probos/substrate/agent.py` — `BaseAgent` ABC, `handle_intent()`, lifecycle methods, `_runtime` reference, `intent_descriptors`
3. `src/probos/consensus/trust.py` — `TrustNetwork.record_outcome()` (confirm `weight` parameter exists — it should, there is an existing "weighted outcome" test), `create_with_prior()`, `get_score()`
4. `src/probos/cognitive/episodic.py` — `EpisodicMemory.store()`, `Episode` type
5. `src/probos/substrate/event_log.py` — `EventLog.log()` signature
6. `src/probos/runtime.py` — `process_natural_language()`, `_handle_unhandled_intent()`, self-mod event flow, `_create_designed_pool()`, `_set_probationary_trust()`
7. `src/probos/types.py` — `IntentResult`, `IntentMessage`, `IntentDescriptor`, `Episode`
8. `src/probos/agents/file_reader.py` — simplest agent, reference for `handle_intent()` output shape
9. `src/probos/substrate/pool.py` — `ResourcePool`, agent access patterns
10. `src/probos/config.py` — `SelfModConfig`, `SystemConfig`

---

## Deliverables

### 1. Add `QAConfig` to `src/probos/config.py`

Add a new config section for the QA subsystem:

```python
class QAConfig(BaseModel):
    """SystemQAAgent configuration."""

    enabled: bool = True                    # QA runs by default when self-mod is enabled
    smoke_test_count: int = 5               # Number of synthetic intents per new agent
    timeout_per_test_seconds: float = 10.0  # Per-intent timeout
    total_timeout_seconds: float = 30.0     # Total QA budget per agent
    pass_threshold: float = 0.6             # Fraction of tests that must pass (3/5)
    trust_reward_weight: float = 1.0        # Weight for trust_network.record_outcome on success
    trust_penalty_weight: float = 2.0       # Weight for trust_network.record_outcome on failure
    flag_on_fail: bool = True               # Emit warning event if agent fails QA
    auto_remove_on_total_fail: bool = False  # Remove agent if 0/N pass (conservative default: off)
```

Add `qa: QAConfig = QAConfig()` to `SystemConfig`.

Add `qa:` section to `config/system.yaml` with defaults commented out (same pattern as `scaling:` and `federation:` sections).

---

### 2. Create `src/probos/agents/system_qa.py` — SystemQAAgent

The SystemQAAgent is a regular `BaseAgent` subclass that lives in a dedicated pool. Unlike other agents, it does not handle user-facing intents — it is triggered internally by the self-mod pipeline.

```python
class SystemQAAgent(BaseAgent):
    agent_type = "system_qa"
    intent_descriptors = [
        IntentDescriptor(
            name="smoke_test_agent",
            params={
                "agent_type": "type name of the agent to test",
                "pool_name": "pool the agent belongs to",
                "intent_name": "intent the agent should handle",
                "intent_params": "example params for the intent",
            },
            description="Run smoke tests against a newly designed agent",
            requires_consensus=False,
            requires_reflect=False,
        ),
    ]
```

#### Core Logic: `async def run_smoke_tests(self, record: DesignedAgentRecord, pool: ResourcePool, config: QAConfig) -> QAReport`

Pass `QAConfig` explicitly — the agent does not read system config directly.

1. **Generate synthetic test cases** via `generate_synthetic_intents(record, config.smoke_test_count) -> list[tuple[str, IntentMessage]]` where the tuple is `(case_type, intent)` with `case_type` being `"happy"`, `"edge"`, or `"error"`.

   Based on the `DesignedAgentRecord` metadata (intent_name, parameters, description), produce `smoke_test_count` synthetic `IntentMessage` objects:
   - **Happy path** (2-3 cases): Valid parameters matching the intent's param schema
   - **Edge case** (1 case): Empty or minimal parameters
   - **Error case** (1 case): Missing required parameters or invalid types

   Test case generation is deterministic from the intent metadata — no LLM call needed.

   **Param type inference (AD-156):** The `params` dict from `IntentDescriptor` maps param names to description strings (e.g., `{"query": "search query text", "url": "target URL"}`). Infer the synthetic value type from the **key name**, not the description:
   - Keys containing `url` or `uri` → `"https://example.com"`, `"not-a-url"`, `""`
   - Keys containing `path`, `file`, `dir` → `"/tmp/test_qa.txt"`, `""`, `"/nonexistent/deep/path"`
   - Keys containing `count`, `num`, `limit`, `size`, `port` → `42`, `0`, `-1`
   - Keys containing `flag`, `enabled`, `verbose` → `True`, `False`
   - All other keys → `"test_value"`, `""`, `None`

   For happy path cases, use the first value from each type. For edge cases, use the second (minimal). For error cases, use the third (invalid/missing). If `smoke_test_count > 3`, generate additional happy path variants by combining different valid values.

   This method must be a standalone, testable method on `SystemQAAgent` — not inlined into `run_smoke_tests`.

2. **Execute each test case.** Pick one agent from the pool, call `agent.handle_intent(intent)` with `asyncio.wait_for(timeout=timeout_per_test)`. Wrap in try/except for all exceptions.

3. **Validate each result** via `validate_result(case_type, result, error) -> bool` — also a standalone testable method.

   A test passes if:
   - For happy path: `result` is an `IntentResult`, `result.success is True`, `result.result is not None`
   - For edge case: `result` is an `IntentResult` (may succeed or fail, but must not crash)
   - For error case: `result` is an `IntentResult` with `result.success is False` and `result.error is not None` (graceful error handling), OR `result is None` (declined — also acceptable)
   - For all cases: No unhandled exception was raised (i.e., `error is None`)

4. **Compute QA verdict.** `pass_rate = passed / total`. If `pass_rate >= pass_threshold`, verdict is `"passed"`. Otherwise `"failed"`.

5. **Return `QAReport`** (new dataclass):

```python
@dataclass
class QAReport:
    agent_type: str
    intent_name: str
    pool_name: str
    total_tests: int
    passed: int
    failed: int
    pass_rate: float
    verdict: str             # "passed" | "failed" | "error"
    test_details: list[dict] # [{case_type: str, passed: bool, error: str | None}, ...]
    duration_ms: float
    timestamp: float
```

#### Integration Points

- **Trust update:** After QA completes, call `trust_network.record_outcome(agent_id, success=passed, weight=reward_weight)` for each passed test, and `record_outcome(agent_id, success=False, weight=penalty_weight)` for each failure. Do this for every agent in the pool (they share the same code, so QA results apply to all).

- **Episodic memory:** Record one `Episode` per QA run:
  ```python
  Episode(
      user_input=f"[SystemQA] Smoke test: {record.intent_name}",
      dag_summary={"node_count": total_tests, "intent_types": [record.intent_name], "has_dependencies": False},
      outcomes=[{"intent": "smoke_test", "success": t["passed"], "status": "completed" if t["passed"] else "failed"} for t in test_details],
      reflection=f"QA {verdict}: {passed}/{total} passed for {agent_type}",
      agent_ids=[a.id for a in pool.agents],
      duration_ms=duration_ms,
  )
  ```

- **Event log:** Emit events through `event_log.log()`:
  - `category="qa", event="smoke_test_started", detail=f"{agent_type}: {total_tests} tests"`
  - `category="qa", event="smoke_test_passed", detail=f"{agent_type}: {passed}/{total}"` on success
  - `category="qa", event="smoke_test_failed", detail=f"{agent_type}: {passed}/{total}"` on failure

- **Flagging:** If QA fails and `flag_on_fail` is True, emit `category="qa", event="agent_flagged", detail=f"{agent_type} failed smoke tests ({passed}/{total})"`. If `auto_remove_on_total_fail` is True and `passed == 0`, call `pool.remove_agent()` for each agent and emit `category="qa", event="agent_removed"`.

---

### 3. Wire into `src/probos/runtime.py`

#### 3a. Create QA pool at boot

In `start()`, after the existing pool creation block:

```python
if self.config.self_mod.enabled and self.config.qa.enabled:
    self._qa_pool = await self.create_pool("system_qa", SystemQAAgent, size=1)
    self._system_qa = self._qa_pool.agents[0]
    self._qa_reports: dict[str, QAReport] = {}  # AD-157: in-memory report store
```

**AD-153:** The QA pool has exactly 1 agent. This is an intentional exception to Design Principle #1 ("No single points of failure"). Justification: QA is internal infrastructure, not a user-facing capability. Its failure is non-critical — the worst case is that a designed agent doesn't get smoke-tested, and the trust network still handles ongoing quality through real-world usage. Adding redundancy here would require consensus on QA results (meta-consensus on meta-agents), adding complexity with no safety benefit.

#### 3b. Add `_run_qa_for_designed_agent()` method

```python
async def _run_qa_for_designed_agent(self, record: DesignedAgentRecord) -> QAReport | None:
    """Run smoke tests for a newly designed agent. Non-blocking — called via create_task after user response."""
    # AD-154: All errors contained — this runs as a fire-and-forget task
    try:
        if not self.config.qa.enabled or not hasattr(self, '_system_qa'):
            return None

        pool = self.pools.get(record.pool_name)
        if not pool or not pool.agents:
            return None

        report = await self._system_qa.run_smoke_tests(record, pool, self.config.qa)

        # AD-157: Store report in-memory for /qa command
        self._qa_reports[record.agent_type] = report

        # Trust updates
        for agent in pool.agents:
            for test in report.test_details:
                weight = self.config.qa.trust_reward_weight if test["passed"] else self.config.qa.trust_penalty_weight
                self.trust_network.record_outcome(agent.id, success=test["passed"], weight=weight)

        # Episodic memory
        if self.episodic_memory:
            episode = Episode(
                id=uuid.uuid4().hex,
                timestamp=time.time(),
                user_input=f"[SystemQA] Smoke test: {record.intent_name}",
                dag_summary={"node_count": report.total_tests, "intent_types": [record.intent_name], "has_dependencies": False},
                outcomes=[{"intent": "smoke_test", "success": t["passed"], "status": "completed" if t["passed"] else "failed"} for t in report.test_details],
                reflection=f"QA {report.verdict}: {report.passed}/{report.total_tests} passed for {record.agent_type}",
                agent_ids=[a.id for a in pool.agents],
                duration_ms=report.duration_ms,
                embedding=[],
            )
            await self.episodic_memory.store(episode)

        # Flagging
        if report.verdict == "failed" and self.config.qa.flag_on_fail:
            await self.event_log.log(
                category="qa", event="agent_flagged",
                detail=f"{record.agent_type} failed smoke tests ({report.passed}/{report.total_tests})"
            )

        # Auto-remove on total failure
        if report.passed == 0 and self.config.qa.auto_remove_on_total_fail:
            for agent in list(pool.agents):
                pool.remove_agent(agent.id)
            await self.event_log.log(
                category="qa", event="agent_removed",
                detail=f"{record.agent_type}: all agents removed after 0/{report.total_tests} passed"
            )

        return report

    except Exception as e:
        # AD-154: QA failure must never crash the runtime or go unlogged
        try:
            await self.event_log.log(
                category="qa", event="qa_error",
                detail=f"QA failed for {record.agent_type}: {repr(e)}"
            )
        except Exception:
            pass  # event log itself failed — nothing more we can do
        return None
```

#### 3c. Trigger QA after self-mod success

In `process_natural_language()`, after the self-mod pipeline succeeds and the retry decomposition completes, schedule QA as a background task:

```python
# After: result = await self._execute_dag(dag, ...)
# Add:
if designed_record is not None and hasattr(self, '_system_qa'):
    asyncio.create_task(self._run_qa_for_designed_agent(designed_record))
```

Use `asyncio.create_task()` so QA does not block the user response. The task runs concurrently — the user gets their answer immediately. **AD-154** ensures exceptions in the task are caught and logged, never silently swallowed.

#### 3d. Exclude QA from user-facing routing (AD-158)

In `_collect_intent_descriptors()`, filter out descriptors from the `system_qa` pool — same pattern used to exclude `red_team` descriptors from the decomposer. The `smoke_test_agent` intent must never appear in the decomposer's system prompt.

In the pool scaler exclusions list (if one exists), add `"system_qa"`. If exclusions are handled differently, ensure the QA pool is excluded from demand-driven scaling.

#### 3e. Add `/qa` shell command

Register a `/qa` command in the shell that displays QA results:

```
/qa              — Show QA status for all designed agents
/qa <agent_type> — Show detailed QA results for a specific agent
```

**AD-157:** The `/qa` command reads from `runtime._qa_reports` (in-memory dict) as its primary data source, NOT from episodic memory string matching. This is fast, typed, and doesn't break if the `[SystemQA]` prefix format changes. Episodic memory stores the durable record for decomposer context; the in-memory dict serves the shell.

Display as a Rich table:

```
╭─── System QA Status ────────────────────────────╮
│ Agent Type          │ Verdict │ Score │ Trust    │
│─────────────────────│─────────│───────│──────────│
│ weather_agent       │ PASSED  │  4/5  │ 0.42 ↑  │
│ text_summarizer     │ FAILED  │  1/5  │ 0.18 ↓  │
╰──────────────────────────────────────────────────╯
```

---

### 4. Create `src/probos/experience/qa_panel.py` — QA rendering

Add a `render_qa_panel()` function that produces the Rich renderable for the `/qa` command. Follow the same pattern as `render_scaling_panel()` or `render_designed_panel()`:

```python
def render_qa_panel(qa_reports: dict[str, QAReport], trust_network: TrustNetwork) -> Panel:
    ...
```

Note the signature takes `dict[str, QAReport]` not `list[Episode]` — it reads from the in-memory report store (AD-157).

Wire into `renderer.py` and `shell.py` following the existing panel registration pattern.

---

### 5. Extend the `/designed` command

Update `render_designed_panel()` to include a "QA" column showing the latest smoke test verdict for each designed agent (if QA was run). Pass `qa_reports` dict alongside the existing parameters. This gives users a single view of designed agent status + quality.

**Important:** Existing `/designed` panel tests must continue to pass. The QA column should show "—" or be omitted when `qa_reports` is empty/None. Update the `render_designed_panel` function signature to accept an optional `qa_reports` parameter with a default of `None` for backward compatibility.

---

### 6. Tests: `tests/test_system_qa.py`

**⚠ Regression mandate:** Every new code path introduced in this phase MUST have automated test coverage. The phase is complete when `uv run pytest tests/ -v` passes with all new tests AND all 820 existing tests. No manual testing, no `live_llm` markers — everything runs against `MockLLMClient` and mock agents.

Write comprehensive tests covering:

#### 6a. Unit tests for `SystemQAAgent`

| Test | What it validates |
|------|-------------------|
| `test_generate_synthetic_intents_happy_path` | Generates correct number of synthetic IntentMessages from intent metadata; happy path cases have valid params |
| `test_generate_synthetic_intents_edge_cases` | Edge case intents have minimal/empty params |
| `test_generate_synthetic_intents_error_cases` | Error case intents have invalid params |
| `test_generate_synthetic_intents_count` | Total generated matches `smoke_test_count` (3, 5, 7 — parametrize) |
| `test_param_type_inference_url_key` | Key containing "url" → URL-type synthetic values (AD-156) |
| `test_param_type_inference_path_key` | Key containing "path" or "file" → path-type synthetic values (AD-156) |
| `test_param_type_inference_numeric_key` | Key containing "count", "num", "limit" → int-type synthetic values (AD-156) |
| `test_param_type_inference_bool_key` | Key containing "flag", "enabled" → bool-type synthetic values (AD-156) |
| `test_param_type_inference_default` | Unknown key name → string-type synthetic values (AD-156) |
| `test_validate_result_success` | Happy path: IntentResult with success=True passes |
| `test_validate_result_graceful_failure` | Error case: IntentResult with success=False, error set passes |
| `test_validate_result_crash` | Unhandled exception fails the test (error is not None) |
| `test_validate_result_none_for_error_case` | IntentResult=None on error case counts as pass (declined) |
| `test_validate_result_none_for_happy_path` | IntentResult=None on happy path counts as fail |
| `test_validate_result_edge_case_success` | Edge case: IntentResult with success=True passes |
| `test_validate_result_edge_case_failure` | Edge case: IntentResult with success=False also passes (no crash = pass) |
| `test_qa_report_structure` | QAReport has all required fields, types correct |
| `test_pass_rate_calculation` | 3/5 → 0.6, verdict "passed" at threshold 0.6 |
| `test_fail_rate_calculation` | 2/5 → 0.4, verdict "failed" at threshold 0.6 |
| `test_pass_rate_boundary` | Exactly at threshold (0.6) → "passed"; one below (0.59) → "failed" |

#### 6b. Integration tests

| Test | What it validates |
|------|-------------------|
| `test_smoke_test_passing_agent` | A well-behaved mock agent passes all smoke tests, QAReport verdict is "passed" |
| `test_smoke_test_failing_agent` | An agent that always raises exceptions fails smoke tests, verdict is "failed" |
| `test_smoke_test_flaky_agent` | An agent that sometimes fails gets correct pass rate (e.g., 3/5) |
| `test_smoke_test_declining_agent` | An agent returning None for all intents — happy path cases fail, error case passes |
| `test_trust_updated_on_qa_pass` | Trust network scores increase after passing QA (verify via `get_score()` before/after) |
| `test_trust_updated_on_qa_fail` | Trust network scores decrease after failing QA |
| `test_trust_weight_asymmetry` | Penalty weight (2.0) causes greater trust change than reward weight (1.0) for same number of tests |
| `test_episodic_memory_recorded` | An Episode is stored with `[SystemQA]` prefix after QA completes |
| `test_episodic_memory_content` | Stored episode has correct `dag_summary`, `outcomes`, `reflection`, `agent_ids` |
| `test_event_log_started` | `smoke_test_started` event emitted when QA begins |
| `test_event_log_passed` | `smoke_test_passed` event emitted when QA passes |
| `test_event_log_failed` | `smoke_test_failed` event emitted when QA fails |
| `test_qa_disabled_skips` | QA does not run when `qa.enabled = False`; no events, no trust changes, no episodes |
| `test_qa_without_selfmod_skips` | QA does not run when self-mod is disabled |
| `test_qa_timeout_handling` | Agent that sleeps beyond `timeout_per_test_seconds` — test times out gracefully, marked as failed, no hang |
| `test_qa_total_timeout` | Agent that sleeps beyond `total_timeout_seconds` — remaining tests skipped, report includes partial results |
| `test_qa_flag_on_failure` | `agent_flagged` event emitted when QA fails and `flag_on_fail=True` |
| `test_qa_no_flag_when_disabled` | No `agent_flagged` event when `flag_on_fail=False` |
| `test_qa_auto_remove_on_total_fail` | Pool emptied when 0/N pass and `auto_remove_on_total_fail=True`; `agent_removed` event emitted |
| `test_qa_no_remove_on_partial_fail` | Pool NOT emptied when 1/5 pass and `auto_remove_on_total_fail=True` (only triggers on 0/N) |
| `test_qa_no_remove_when_disabled` | Pool NOT emptied when 0/N pass and `auto_remove_on_total_fail=False` |
| `test_qa_report_stored_in_memory` | After QA runs, `runtime._qa_reports[agent_type]` contains the QAReport (AD-157) |
| `test_qa_report_overwritten_on_rerun` | Second QA run for same agent_type overwrites the first report |

#### 6c. Error containment tests (AD-154)

| Test | What it validates |
|------|-------------------|
| `test_qa_task_exception_logged` | If `run_smoke_tests` raises, `qa_error` event is logged and runtime continues |
| `test_qa_task_exception_no_crash` | Exception in QA background task does not propagate to the calling coroutine |
| `test_qa_empty_pool_no_crash` | QA gracefully returns None if designed pool is empty (agents removed between design and QA) |
| `test_qa_missing_pool_no_crash` | QA gracefully returns None if pool name doesn't exist in `self.pools` |

#### 6d. Routing exclusion tests (AD-158)

| Test | What it validates |
|------|-------------------|
| `test_qa_does_not_block_user_response` | The `asyncio.create_task` pattern — `process_natural_language` returns before QA finishes (use a slow mock agent and verify return time) |
| `test_qa_pool_not_in_intent_descriptors` | `_collect_intent_descriptors()` does NOT include `smoke_test_agent` |
| `test_qa_agent_not_in_decomposer_prompt` | After boot with QA enabled, decomposer system prompt does NOT contain "smoke_test_agent" |
| `test_qa_pool_excluded_from_scaler` | QA pool not affected by demand-driven scaling |
| `test_qa_pool_created_at_boot` | When self_mod.enabled and qa.enabled, `system_qa` pool exists with 1 agent |
| `test_qa_pool_not_created_when_disabled` | When qa.enabled=False, no `system_qa` pool |

#### 6e. Config tests

| Test | What it validates |
|------|-------------------|
| `test_qa_config_defaults` | Default config values match spec (enabled=True, smoke_test_count=5, pass_threshold=0.6, etc.) |
| `test_qa_config_in_system_config` | `SystemConfig` includes `qa: QAConfig` field |
| `test_qa_config_from_yaml` | Config loads from YAML with custom QA values |
| `test_qa_config_missing_uses_defaults` | Missing `qa:` section in YAML → defaults applied |

#### 6f. Experience layer tests

| Test | What it validates |
|------|-------------------|
| `test_render_qa_panel_with_reports` | `render_qa_panel()` with populated reports dict renders Rich table with correct columns |
| `test_render_qa_panel_empty` | `render_qa_panel()` with empty dict shows "No QA results" message |
| `test_render_qa_panel_mixed_verdicts` | Panel correctly shows PASSED and FAILED with different styling |
| `test_qa_shell_command_registered` | `/qa` appears in shell COMMANDS dict |
| `test_qa_shell_renders_panel` | `/qa` command calls `render_qa_panel` and outputs to console |
| `test_qa_shell_with_agent_type` | `/qa weather_agent` shows detailed view for specific agent |
| `test_qa_shell_help_includes_qa` | `/help` output includes `/qa` command |
| `test_designed_panel_qa_column` | `render_designed_panel()` with `qa_reports` param shows QA column |
| `test_designed_panel_qa_column_none` | `render_designed_panel()` with `qa_reports=None` renders without QA column (backward compat) |
| `test_designed_panel_qa_column_no_report` | Agent in designed list but not in QA reports → shows "—" in QA column |

#### 6g. Existing test regression

| Test | What it validates |
|------|-------------------|
| `test_existing_designed_panel_unchanged` | All existing `render_designed_panel` tests pass without modification (the optional `qa_reports` parameter defaults to None) |
| `test_existing_selfmod_flow_unchanged` | Full self-mod pipeline integration tests still pass — QA is additive, not modifying the existing flow |
| `test_existing_shell_commands_unchanged` | All existing shell command tests still pass |
| `test_runtime_status_includes_qa` | `runtime.status()` dict includes `qa` key with enabled state and report count |
| `test_runtime_status_without_qa` | When QA disabled, `runtime.status()` still works (no KeyError) |

---

## ⚠ Test Execution Constraints

- **All tests must use `MockLLMClient`.** No `@pytest.mark.live_llm` markers in this phase.
- **Mock agents for QA targets.** Create simple mock agent classes (e.g., `PassingMockAgent`, `FailingMockAgent`, `FlakyMockAgent`, `SlowMockAgent`) in the test file. These should subclass `BaseAgent` with minimal `handle_intent` implementations.
- **No network, no filesystem side effects.** All tests run in `pytest` with temp dirs and in-memory state.
- **Target:** 60+ new tests. The phase is not complete until `uv run pytest tests/ -v` shows 880+ tests passing (820 existing + 60+ new) with 0 failures.

---

## What This Phase Does NOT Include

- **LLM-generated test cases.** Test case generation is deterministic from intent metadata. A future phase could use the LLM to generate more sophisticated test scenarios, but the simple approach is more reliable and doesn't add latency.
- **QA for skill additions.** `handle_add_skill()` modifies existing `SkillBasedAgent` instances rather than creating new agent types. Skill QA is a different pattern (test the skill function, not the agent) and should be a separate follow-up.
- **Redesign loop.** If QA fails, the system flags the agent but does not automatically redesign it. A redesign loop (capture failure info → re-prompt AgentDesigner → re-validate) is a natural follow-up but adds complexity. The trust network already handles gradual demotion of failing agents.
- **QA for existing (non-designed) agents.** The system's built-in agents are covered by the pytest suite. SystemQAAgent only tests self-created agents.
- **Modifications to `TrustNetwork.record_outcome()`.** The existing `weight` parameter is sufficient. Do not change the trust interface.

---

## Build Order

1. `QAConfig` in `config.py` + config tests (verify defaults, YAML loading)
2. `QAReport` dataclass in `types.py` or `system_qa.py`
3. `SystemQAAgent` class with `generate_synthetic_intents()` and `validate_result()` + unit tests
4. `run_smoke_tests()` integration + integration tests with mock agents
5. Runtime wiring (`_run_qa_for_designed_agent`, pool creation, routing exclusion) + error containment tests + routing exclusion tests
6. Experience layer (`qa_panel.py`, `/qa` command, `/designed` QA column) + experience tests
7. Full regression: `uv run pytest tests/ -v` — all 880+ tests pass

Do NOT proceed to step N+1 until step N's tests pass.

---

## Existing Infrastructure Leveraged

| Component | How SystemQAAgent uses it |
|-----------|--------------------------|
| `SelfModificationPipeline` | Provides `DesignedAgentRecord` with intent metadata, pool name, agent class |
| `TrustNetwork` | `record_outcome(agent_id, success, weight)` for QA results, `get_score()` for display |
| `EpisodicMemory` | `store()` to record QA episodes for decomposer context |
| `EventLog` | `log()` for QA lifecycle events (started, passed, failed, flagged, removed, error) |
| `ResourcePool` | Access to agents in the designed pool for testing |
| `BaseAgent.handle_intent()` | Standard agent contract — QA calls the same interface the mesh does |
| `IntentResult` | Output shape validation against the existing type |
| `PoolScaler` exclusions | QA pool excluded from demand-driven scaling |
| `asyncio.create_task` | Non-blocking QA execution with error containment |

---

## Architectural Notes

- The SystemQAAgent is a meta-agent: it operates on other agents rather than on external resources. This is consistent with ProbOS's self-referential architecture (IntrospectionAgent already does this for explanation/health queries).

- QA results feeding into the trust network create a feedback loop: smoke-test failures lower trust → Hebbian routing sends less traffic → fewer real-world failures → trust-aware scale-down removes the agent. The system is self-correcting.

- The `[SystemQA]` prefix in episodic memory entries lets the decomposer distinguish system-internal history from user-facing history when building context for future decompositions.

- **AD-153 — Single-agent QA pool exception.** Design Principle #1 states "No single points of failure. Ever." The QA pool intentionally violates this with a single agent. Justification: (a) QA is not user-facing — its failure degrades internal quality assurance but does not affect any user request, (b) the trust network provides a redundant quality signal through real-world usage even if QA never runs, (c) adding consensus to QA would require meta-consensus on meta-agents, adding complexity that buys nothing for safety. If this exception proves wrong in practice, scaling the QA pool to 2 is a one-line config change.

- **AD-157 — Dual storage.** QA reports live in two places: `runtime._qa_reports` (typed dict, fast, primary query path for `/qa`) and episodic memory (durable, provides decomposer context). This avoids fragile string-matching on `[SystemQA]` prefixes for shell commands while still giving the cognitive layer access to QA history.
