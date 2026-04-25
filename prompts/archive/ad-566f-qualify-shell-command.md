# AD-566f: `/qualify` Shell Command

**Type:** Additive feature (new command module + shell wiring)
**Risk:** Low — read-only inspection + on-demand test trigger via existing harness
**Tests:** Targeted only (new command module)

## Context

The AD-566 series delivered a 3-tier qualification battery (harness, tests, drift detection) but provides no manual trigger or inspection from the shell. The `DriftScheduler.run_now()` method exists but is unreachable from the Captain's console. We need a `/qualify` shell command to:

1. Trigger qualification tests on demand (establish baselines, pre/post comparison)
2. Inspect current baselines and latest results
3. View per-agent summaries

## Architecture (read before coding)

**Shell command pattern** — follow the existing convention exactly:

- Command module: `src/probos/experience/commands/commands_qualification.py`
- Single async function: `cmd_qualify(runtime, console, args)`
- Import in `shell.py` line ~17: add `commands_qualification` to the import block
- COMMANDS dict entry (~line 89): `"/qualify": "Run qualification tests or view results (/qualify [run|status|agent <id>])"`
- Handler dict entry (~line 264): `"/qualify": lambda: commands_qualification.cmd_qualify(rt, con, arg)`

**Runtime attributes** (all private, accessed via underscore):
- `runtime._qualification_harness` — `QualificationHarness` or `None`
- `runtime._qualification_store` — `QualificationStore` or `None`
- `runtime._drift_scheduler` — `DriftScheduler` or `None`

**Key APIs:**
- `DriftScheduler.run_now(agent_ids=None)` → `list[DriftReport]` — runs all configured tiers for all crew agents (or specified list), returns drift reports
- `QualificationHarness.run_all(agent_id, runtime)` → `list[TestResult]` — runs all tests for one agent
- `QualificationHarness.run_collective(tier, runtime)` → `list[TestResult]` — runs tier 3 crew-wide
- `QualificationHarness.registered_tests` → `dict[str, QualificationTest]` — test registry
- `QualificationStore.get_agent_summary(agent_id)` → `dict` with keys: `agent_id`, `tests_run`, `tests_passed`, `pass_rate`, `baseline_set`, `latest_results`
- `QualificationStore.get_baseline(agent_id, test_name)` → `TestResult | None`
- `QualificationStore.get_latest(agent_id, test_name)` → `TestResult | None`
- `QualificationStore.get_history(agent_id, test_name, limit=20)` → `list[TestResult]`
- `DriftScheduler._get_crew_agent_ids()` → `list[str]` — enumerates healthy crew agents from pools

**TestResult dataclass** (from `probos.cognitive.qualification`):
```python
@dataclass(frozen=True)
class TestResult:
    agent_id: str
    test_name: str
    tier: int
    score: float           # 0.0–1.0
    passed: bool
    timestamp: str         # ISO 8601
    duration_ms: float
    is_baseline: bool
    details: dict[str, Any]
    error: str | None = None
    id: str = ""           # UUID, set by store
```

**CREW_AGENT_ID** constant: `"__crew__"` (from `probos.cognitive.qualification`)

## Deliverables

### D1: `src/probos/experience/commands/commands_qualification.py`

New module with a single public function `cmd_qualify`. Subcommands:

#### `/qualify` or `/qualify status`
Show overview: number of registered tests per tier, number of crew agents, whether baselines exist, last drift run time.

```python
async def cmd_qualify(runtime: ProbOSRuntime, console: Console, args: str) -> None:
```

Use Rich tables/panels for output. Pattern after `cmd_qa`.

**Status output should include:**
- Registered tests grouped by tier (tier 1, tier 2, tier 3) with test names
- Number of crew agents detected (via `_drift_scheduler._get_crew_agent_ids()` if available)
- Whether drift scheduler is running
- Last run time (from `_drift_scheduler._last_run_time` if set)

#### `/qualify run`
Trigger `DriftScheduler.run_now()` for all crew agents. Print a Rich table of results:

| Agent | Test | Tier | Score | Pass | Baseline |
|-------|------|------|-------|------|----------|

After running, print summary: `X agents, Y tests, Z passed, W baselines established`.

If `_drift_scheduler` is None, print error and return.

Use `console.print("[dim]Running qualification battery...[/dim]")` before starting.

#### `/qualify run <callsign>`
Run all tests for a specific agent. Resolve callsign to agent_id by scanning `runtime.registry`. Use `QualificationHarness.run_all(agent_id, runtime)` directly.

Print results table for that agent only.

#### `/qualify agent <callsign>`
Show the agent summary from `QualificationStore.get_agent_summary(agent_id)`. Include:
- Total tests run, pass rate
- Baseline status
- Latest result per test (test name, score, passed, timestamp)

#### `/qualify baselines`
Show all established baselines across all crew agents. Query the store for each agent × each test and show which have baselines set.

Rich table: Agent | Test | Baseline Score | Baseline Date

### D2: Shell wiring in `src/probos/experience/shell.py`

1. Add import at line ~17 (after `commands_introspection`):
   ```python
   commands_qualification,
   ```

2. Add to COMMANDS dict (after `/gap` line ~76):
   ```python
   "/qualify": "Run qualification tests or view results (/qualify [run|status|agent <id>|baselines])",
   ```

3. Add to handler dict (after `/gap` line ~240):
   ```python
   "/qualify": lambda: commands_qualification.cmd_qualify(rt, con, arg),
   ```

### D3: Tests — `tests/test_qualify_command.py`

Test the command module with mock runtime. Follow pattern from other command tests.

**Test cases:**
1. `test_status_no_harness` — runtime has no `_qualification_harness`, prints error
2. `test_status_with_harness` — shows registered tests and tier counts
3. `test_run_triggers_drift_scheduler` — calls `run_now()`, prints results
4. `test_run_specific_agent` — resolves callsign, runs `run_all` for that agent
5. `test_agent_summary` — calls `get_agent_summary`, renders table
6. `test_baselines_empty` — no baselines yet, shows empty message
7. `test_unknown_subcommand` — prints usage help

**Mock setup pattern:**
```python
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from rich.console import Console
from io import StringIO

def _make_runtime(**kwargs):
    rt = SimpleNamespace(
        _qualification_harness=kwargs.get("harness"),
        _qualification_store=kwargs.get("store"),
        _drift_scheduler=kwargs.get("scheduler"),
        registry=kwargs.get("registry", {}),
    )
    return rt

def _make_console():
    buf = StringIO()
    return Console(file=buf, width=120), buf
```

## Constraints

- **No new dependencies.** Rich is already available.
- **No LLM calls.** This is pure inspection + triggering existing infrastructure.
- **Log-and-degrade.** If harness/store/scheduler is None, print a helpful message, don't crash.
- **Callsign resolution:** Iterate `runtime.registry` values, match on `agent.callsign` (case-insensitive). If not found, try matching on `agent.agent_type`. If still not found, try treating the arg as a raw agent_id.
- **Fail Fast principle:** Validate subcommand early, print usage on unknown input.
- **Keep it simple.** No pagination, no filtering, no export. Just the tables.

## Verification

```bash
python -m pytest tests/test_qualify_command.py -v
```

All tests must pass. No modifications to existing test files.
