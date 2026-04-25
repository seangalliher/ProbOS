# AD-519: Extract shell.py Command Handlers

## Problem

`ProbOSShell` in `src/probos/experience/shell.py` is 1,883 lines with 62 methods in a single class — the last remaining god object. It has the lowest test coverage in the codebase (64%). Every slash command handler, 1:1 session management, approval callbacks, and REPL lifecycle are mixed together. This violates single responsibility and makes the file impossible to test in isolation.

## Architecture

Extract command handlers into focused modules under `src/probos/experience/commands/`. Each module exposes standalone async functions that take `runtime`, `console`, and `args` as parameters. `ProbOSShell` becomes a thin REPL core (~210 lines) that dispatches to the extracted modules.

### Pattern

Each command module follows this pattern:

```python
"""Status commands for ProbOSShell."""
from __future__ import annotations
import logging
from typing import Any
from rich.console import Console

logger = logging.getLogger(__name__)

async def cmd_status(runtime: Any, console: Console, args: str) -> None:
    """Handle /status command."""
    from probos.experience import panels
    console.print(panels.render_status(runtime))
```

Commands that need shell state (like session fields) take additional parameters. The key principle: **no command function should import or reference `ProbOSShell`** — they operate on runtime + console + explicit parameters.

## Extraction Plan

### Package structure

Create `src/probos/experience/commands/__init__.py` (empty or with a registry dict).

### Module 1: `commands_status.py` (~90 lines)

Extract these methods as standalone functions:
- `_cmd_status` → `cmd_status(runtime, console, args)`
- `_cmd_agents` → `cmd_agents(runtime, console, args)`
- `_cmd_ping` → `cmd_ping(runtime, console, args, start_time)` — needs `self._start_time`
- `_cmd_scaling` → `cmd_scaling(runtime, console, args)`
- `_cmd_federation` → `cmd_federation(runtime, console, args)`
- `_cmd_peers` → `cmd_peers(runtime, console, args)`
- `_cmd_credentials` → `cmd_credentials(runtime, console, args)`
- `_cmd_debug` → `cmd_debug(runtime, console, args)`
- `_cmd_help` → `cmd_help(console, commands_dict)` — needs `COMMANDS` dict
- `_format_uptime` → `format_uptime(seconds)` (pure helper, no self)

### Module 2: `commands_plan.py` (~305 lines)

The heaviest handlers. Extract:
- `_cmd_plan` → `cmd_plan(runtime, console, renderer, args)`
- `_cmd_approve` → `cmd_approve(runtime, console, renderer, args)` — needs `self.renderer`
- `_cmd_reject` → `cmd_reject(runtime, console, args)`
- `_cmd_feedback` → `cmd_feedback(runtime, console, args)`
- `_cmd_correct` → `cmd_correct(runtime, console, args)`

These use `self.renderer` (ExecutionRenderer) — pass it as a parameter.

### Module 3: `commands_directives.py` (~305 lines)

Extract:
- `_cmd_orders` → `cmd_orders(runtime, console, args)`
- `_cmd_order` → `cmd_order(runtime, console, args)`
- `_cmd_directives` → `cmd_directives(runtime, console, args)`
- `_cmd_revoke` → `cmd_revoke(runtime, console, args)`
- `_cmd_amend` → `cmd_amend(runtime, console, args)`
- `_cmd_imports` → `cmd_imports(runtime, console, args)`
- `_get_callsign` → `get_callsign(agent_type)` (pure helper)

### Module 4: `commands_autonomous.py` (~175 lines)

Extract:
- `_cmd_conn` → `cmd_conn(runtime, console, args)`
- `_cmd_night_orders` → `cmd_night_orders(runtime, console, args)`
- `_cmd_watch` → `cmd_watch(runtime, console, args)`

### Module 5: `commands_memory.py` (~65 lines)

Extract:
- `_cmd_memory` → `cmd_memory(runtime, console, args)`
- `_cmd_history` → `cmd_history(runtime, console, args)`
- `_cmd_recall` → `cmd_recall(runtime, console, args)`
- `_cmd_dream` → `cmd_dream(runtime, console, args)`

### Module 6: `commands_knowledge.py` (~85 lines)

Extract:
- `_cmd_knowledge` → `cmd_knowledge(runtime, console, args)`
- `_cmd_rollback` → `cmd_rollback(runtime, console, args)`
- `_cmd_search` → `cmd_search(runtime, console, args)`
- `_cmd_anomalies` → `cmd_anomalies(runtime, console, args)`
- `_cmd_scout` → `cmd_scout(runtime, console, args)`

### Module 7: `commands_llm.py` (~145 lines)

Extract:
- `_cmd_models` → `cmd_models(runtime, console, args)`
- `_cmd_registry` → `cmd_registry(runtime, console, args)`
- `_cmd_tier` → `cmd_tier(runtime, console, args)`

### Module 8: `commands_introspection.py` (~75 lines)

Extract:
- `_cmd_weights` → `cmd_weights(runtime, console, args)`
- `_cmd_gossip` → `cmd_gossip(runtime, console, args)`
- `_cmd_designed` → `cmd_designed(runtime, console, args)`
- `_cmd_qa` → `cmd_qa(runtime, console, args)`
- `_cmd_prune` → `cmd_prune(runtime, console, args)`
- `_cmd_log` → `cmd_log(runtime, console, args)`
- `_cmd_attention` → `cmd_attention(runtime, console, args)`
- `_cmd_cache` → `cmd_cache(runtime, console, args)`

### Module 9: `session.py` (~150 lines)

Session management has its own state. Create a `SessionManager` class:

```python
class SessionManager:
    """Manages 1:1 @callsign agent sessions."""
    def __init__(self, runtime, console, renderer):
        self.callsign: str = ""
        self.agent_id: str = ""
        self.agent_type: str = ""
        self.department: str = ""
        self.history: list = []

    @property
    def active(self) -> bool:
        return bool(self.callsign)

    async def handle_at(self, text, runtime, console) -> None: ...
    async def handle_at_parsed(self, callsign, message, runtime, console) -> None: ...
    async def handle_message(self, text, runtime, console, renderer) -> None: ...
    def exit_session(self, console) -> None: ...  # /bridge
```

Shell replaces the 5 `_session_*` fields with `self.session = SessionManager(...)`.

### Module 10: `approval_callbacks.py` (~115 lines)

Extract as standalone functions:
- `_user_escalation_callback` → `user_escalation_callback(console, *args)`
- `_user_self_mod_approval` → `user_self_mod_approval(console, *args)`
- `_user_import_approval` → `user_import_approval(console, *args)`
- `_user_dep_install_approval` → `user_dep_install_approval(console, *args)`

These only use `self.console` — pure UI interaction, no runtime dependency.

## Updating shell.py

After extraction, shell.py should contain:
1. `COMMANDS` dict (slash command help text)
2. `__init__` — creates runtime, console, renderer, SessionManager
3. `_compute_health` / `_build_prompt` — prompt construction
4. `run` — REPL loop
5. `execute_command` — top-level dispatch (NL vs slash vs @callsign)
6. `_dispatch_slash` — slash command routing table, now importing from command modules
7. `_handle_nl` — natural language passthrough

### Dispatch table pattern

```python
from probos.experience.commands import (
    commands_status, commands_plan, commands_directives,
    commands_autonomous, commands_memory, commands_knowledge,
    commands_llm, commands_introspection,
)
from probos.experience.commands.approval_callbacks import (
    user_escalation_callback, user_self_mod_approval,
    user_import_approval, user_dep_install_approval,
)

async def _dispatch_slash(self, cmd: str, args: str) -> None:
    rt, con = self.runtime, self.console
    dispatch = {
        "status": lambda: commands_status.cmd_status(rt, con, args),
        "agents": lambda: commands_status.cmd_agents(rt, con, args),
        "ping": lambda: commands_status.cmd_ping(rt, con, args, self._start_time),
        "plan": lambda: commands_plan.cmd_plan(rt, con, self.renderer, args),
        "approve": lambda: commands_plan.cmd_approve(rt, con, self.renderer, args),
        # ... etc
    }
    handler = dispatch.get(cmd)
    if handler:
        await handler()
    else:
        con.print(f"[yellow]Unknown command: /{cmd}[/yellow]")
```

## Testing

### Existing tests
- Find all tests that test shell commands: `grep -rn "ProbOSShell\|_cmd_\|_dispatch" tests/`
- Ensure they still pass after extraction — these test behavior, not internal method names
- Update any tests that directly call `shell._cmd_*` methods to use the new module functions

### New tests
Each extracted module should have at minimum:
- 1 test per command function verifying it runs without error with a mock runtime
- Use `MagicMock(spec=ProbOSRuntime)` — **mandatory**, per engineering guidelines
- `SessionManager` needs tests for: enter session, handle message, exit session, active property

### Test file naming
- `tests/test_commands_status.py`
- `tests/test_commands_plan.py`
- etc. — one per module

## Constraints

1. **Pure structural refactor** — zero behavior changes. Every command must work identically before and after.
2. **No new features** — don't improve, refactor, or clean up the extracted code. Move it verbatim.
3. **Preserve all imports** — deferred imports inside methods stay deferred in the new location.
4. **Mock discipline** — all new tests use `spec=RealClass` on mocks.
5. **Exception handler logging** — if any extracted code has `logger.debug` in exception handlers, upgrade to `logger.warning` (per BF-078 engineering guidance).

## Validation

1. All existing tests pass: `pytest tests/ -x -q`
2. `wc -l src/probos/experience/shell.py` should be ~200-250 lines
3. `ls src/probos/experience/commands/` shows 10 module files + `__init__.py`
4. Each extracted module is importable independently
5. Manual smoke test: `/status`, `/agents`, `/ping`, `/plan`, `/orders`, `/history`, `@echo hello`, `/bridge` all work

## Reference

- **Prior art:** AD-515 (runtime.py → 5 modules), AD-516 (api.py → 16 routers), AD-517 (start() → 8 phases), AD-518 (shim elimination)
- **Wave 3 pattern:** Extract → standalone module → pass dependencies as parameters → thin dispatch in original file
- **Current state:** shell.py 1,883 lines, 64% coverage
- **Target:** shell.py ~210 lines (−89%), coverage gap addressable per-module
