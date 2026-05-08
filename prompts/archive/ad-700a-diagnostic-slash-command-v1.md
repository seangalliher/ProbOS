# AD-700a v1 — `/diagnostic` slash command in the HXI shell

**Issue:** [#507](https://github.com/seangalliher/ProbOS/issues/507)
**Type:** Architecture Decision (HXI surface for AD-700)
**Depends on:** AD-700 (DiagnosticLevel enum + parse_level shipped at `src/probos/agents/medical/diagnostic_levels.py`).
**Wave:** 129

## Goal

The Captain currently has no first-class shell entry point for AD-700 multi-level diagnostics — diagnoses can only be triggered as raw NL or via Medical alerts. AD-700a adds `/diagnostic <level> [target]` to the HXI shell, parses the level via the **module-level** `parse_level()` helper at `agents/medical/diagnostic_levels.py:69` (NOT a `DiagnosticLevel.parse_level()` method — the dispatch's reference shape is wrong; see Verified-Against-Codebase below), issues a `diagnose_system` intent through the canonical Captain → domain agent dispatch path (pool lookup + `agent.handle_intent`), and renders the structured diagnosis in a panel.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/agents/medical/diagnostic_levels.py:30–40` defines `class DiagnosticLevel(str, Enum)` with members `L5/L4/L3/L2/L1`.
- ✅ `src/probos/agents/medical/diagnostic_levels.py:71` defines a **module-level** `def parse_level(value, *, default=DiagnosticLevel.L3) -> DiagnosticLevel`. **The dispatch's reference to `DiagnosticLevel.parse_level()` is incorrect** — `parse_level` is a module-level function, not a method on the enum. This prompt uses the correct symbol shape.
- ✅ `src/probos/agents/medical/diagnostician.py:42–58` defines `IntentDescriptor(name="diagnose_system", params={"focus": ..., "level": "optional diagnostic depth L5|L4|L3|L2|L1 (default L3)"})`. The intent already accepts `level` and `focus`.
- ✅ `src/probos/experience/shell.py:229–305` defines `_dispatch_slash` as a single dict-based router. Existing handlers follow the pattern `"/X": lambda: commands_<X>.cmd_<X>(rt, con, arg)` — see `/clinical` at `:301`.
- ✅ `src/probos/experience/shell.py:25` imports the command modules via `from probos.experience.commands import (..., commands_clinical, ...)`. New module follows the same import convention.
- ✅ `src/probos/experience/commands/commands_clinical.py:1–100` is the canonical template for a new shell command module: top-level docstring, module-private `_USAGE` constant, `cmd_<name>(runtime, console, args)` async entry point, sub-helpers for sub-arguments.
- ✅ `src/probos/experience/panels.py` exposes module-level `render_*` functions that return `rich.panel.Panel` instances (e.g. `render_dag_result` at `:625`, `render_status_panel` at `:76`). New diagnostic panel follows the same shape.
- ✅ Canonical Captain → domain agent dispatch path: `src/probos/experience/commands/commands_knowledge.py:130-148` (the scout precedent). Pattern: `pool = runtime.pools.get("<pool_name>")` → `pool.healthy_agents[0]` → `agent = pool.registry.get(agent_id)` → `await agent.handle_intent(IntentMessage(intent=..., params=...))`. This is the exact shape AD-700a uses; no `runtime.intent_bus.broadcast()` indirection needed.
- ✅ DiagnosticianAgent pool name is `medical_diagnostician`: verified at `src/probos/startup/fleet_organization.py:66` (`pool_names={"medical_diagnostician", "medical_surgeon", "medical_pharmacist", "medical_pathologist"}`).
- ✅ `IntentMessage` is constructed with kwargs `intent=`, `params=` (and optional `target_agent_id=`, `context=`, `ttl_seconds=`). Verified across `commands_knowledge.py:142-146` and `experience/commands/session.py:110-117`.
- ✅ `self.COMMANDS` help registry at `src/probos/experience/shell.py:54-110` — single dict-literal initialized at class scope. New entries are added by extending the dict literal in place; consumed by `commands_status.cmd_help(con, self.COMMANDS)` at `:249` and `:418`.

## Scope

Add the slash command, its handler module, and one new panel renderer. Do not modify `DiagnosticianAgent`, `parse_level`, or the AD-700 enum. Do not change the `diagnose_system` intent shape — pass `level` as a string param exactly as the existing IntentDescriptor declares.

## Deliverables

### D1. New module `src/probos/experience/commands/commands_diagnostic.py`

Mirror the shape of `commands_clinical.py`. Module docstring at top:

```python
"""AD-700a: `/diagnostic` slash command surface.

Captain entry point for AD-700 multi-level diagnostics. Parses the
``<level>`` argument via the canonical ``parse_level()`` helper from
``probos.agents.medical.diagnostic_levels``; issues a ``diagnose_system``
intent (kwargs: ``level``, ``focus``); renders the structured diagnosis
result in a panel via ``panels.render_diagnostic_result``.

Subcommands:
  /diagnostic                  Help / usage
  /diagnostic <level>          Ship-wide diagnose at depth (L5..L1 or 1..5)
  /diagnostic <level> <focus>  Focused diagnose (e.g. ``/diagnostic L2 trust_network``)
"""
```

Module-level constant (mirrors `commands_clinical._USAGE` and the other slash command modules):

```python
_USAGE = (
    "Usage: /diagnostic [<level>] [<focus>]\n"
    "  level: L5..L1 (or 1..5); default L3 if omitted/unknown\n"
    "  focus: optional subsystem (e.g. trust_network, hebbian_router)\n"
    "Examples: /diagnostic | /diagnostic L2 | /diagnostic L1 trust_network"
)
```

`cmd_diagnostic(runtime, console, args: str) -> None`:

1. Parse `args.split(maxsplit=1)`. If empty, print `_USAGE` and return.
2. Call `parse_level(level_token)` — graceful fallback to `L3` is built in.
3. Build the `diagnose_system` intent params: `{"level": level.value, "focus": focus_or_empty}`.
4. Issue the intent via the canonical Captain → domain agent dispatch path (pool lookup + `agent.handle_intent`), mirroring `commands_knowledge.py:130-148`:

   ```python
   from probos.types import IntentMessage

   pool = runtime.pools.get("medical_diagnostician")
   if not pool or not pool.healthy_agents:
       console.print("[yellow]Diagnostician agent not available[/yellow]")
       return
   agent_id = pool.healthy_agents[0]
   agent = pool.registry.get(agent_id)
   if not agent:
       console.print("[yellow]Diagnostician agent not found in registry[/yellow]")
       return
   intent_result = await agent.handle_intent(IntentMessage(
       intent="diagnose_system",
       params={"level": level.value, "focus": focus_or_empty},
   ))
   result = intent_result.result if intent_result else None
   ```

   This path preserves the canonical Captain dispatch (clearance and audit flow through `agent.handle_intent`'s standard machinery — no bypass).
5. Render the structured result via `panels.render_diagnostic_result(result or {}, level=level)` and print it to `console`.
6. On any exception below `cmd_diagnostic`'s top-level: log a warning and print a one-line `[red]` error to the console; never propagate (matches `/clinical` and other slash commands).

### D2. New panel renderer in `src/probos/experience/panels.py`

```python
def render_diagnostic_result(
    result: dict[str, Any],
    *,
    level: "DiagnosticLevel",
) -> Panel:
    """AD-700a: Render a `diagnose_system` result for the HXI shell.

    ``result`` is the structured diagnosis dict produced by DiagnosticianAgent
    (severity, category, affected_components, root_cause, evidence,
    recommended_treatment, treatment_intent). Header line shows the level
    name and ``expected_duration_label`` (from DiagnosticLevel) so the
    Captain immediately sees the depth that was run.
    """
```

Header line: `"Diagnostic [bold]L{rank}[/bold] (depth: {depth_rank}/5, {expected_duration_label})"`.
Body: severity-tinted (`low/medium/high/critical` -> appropriate `rich` color), then the structured fields in a `Table` with two columns. If `result` is missing keys, render `"--"` placeholders rather than crashing.

Place adjacent to other domain panels (e.g. near `render_dag_result`).

### D3. Wire into `_dispatch_slash` in `src/probos/experience/shell.py`

Add the import alongside the other `commands_*` imports at the top of the file:

```python
from probos.experience.commands import (
    ...,
    commands_diagnostic,
    ...,
)
```

Add to the handler dict in `_dispatch_slash`:

```python
"/diagnostic": lambda: commands_diagnostic.cmd_diagnostic(rt, con, arg),
```

Add an entry to `self.COMMANDS` (the help registry, dict-literal at `shell.py:54-110`). Insert near `/clinical`:

```python
"/diagnostic": "Run a multi-level system diagnostic (/diagnostic [<level>] [<focus>]) — AD-700a",
```

### D4. Tests in `tests/test_ad700a_diagnostic_slash_command.py`

Minimum 8 tests. Use `pytest-asyncio` and Rich's `Console(record=True)` capture pattern (see `test_ad635e_clinical_command.py` for a sibling shape if it exists; otherwise use `from io import StringIO; Console(file=StringIO())`):

1. `test_cmd_diagnostic_no_args_prints_usage` — empty args -> usage text in capture.
2. `test_cmd_diagnostic_parses_level_token` — `args="L2 trust_network"` produces an intent with `level="L2"` and `focus="trust_network"`. Use a fake intent bus / runtime stub.
3. `test_cmd_diagnostic_numeric_level_token` — `args="3"` parses to `L3` (verifies `parse_level("3")` integration).
4. `test_cmd_diagnostic_unknown_level_falls_back_to_l3` — `args="banana"` — `parse_level` returns `L3`; intent is still issued.
5. `test_cmd_diagnostic_no_focus_passes_empty` — `args="L1"` — intent params `level="L1"`, `focus=""`.
6. `test_cmd_diagnostic_renders_panel_on_success` — runtime stub returns a structured result; Rich capture contains "Diagnostic" header and at least one of the structured field labels.
7. `test_cmd_diagnostic_runtime_failure_prints_red_error` — runtime stub raises; capture contains "[red]" prefix and no traceback.
8. `test_dispatch_slash_routes_diagnostic` — instantiate the shell with a stub runtime, drive `_dispatch_slash("/diagnostic L3")`, confirm `cmd_diagnostic` is invoked. Use `monkeypatch.setattr("probos.experience.commands.commands_diagnostic.cmd_diagnostic", <fake>)` (patch the **module-level attribute** in `commands_diagnostic`, not the symbol imported into `shell.py`); `_dispatch_slash` resolves the attribute at call time via the module reference, so this patches the path the shell actually invokes.

## Non-Goals

- Do NOT modify `DiagnosticianAgent`, `parse_level`, `DiagnosticLevel`, or any AD-700 substrate.
- Do NOT add a new EventType — the existing intent path emits everything that's needed.
- Do NOT change `BaseAgent`, `IntentMessage`, `RuntimeProtocol`.
- Do NOT add a new `/medical` or `/health` namespace — `/diagnostic` is the surface.
- Do NOT add HXI React/UI code — slash command is shell-only in v1.
- Do NOT bypass the canonical Captain intent path (clearance/audit must continue to flow).

## Acceptance

- Focused: `pytest tests/test_ad700a_diagnostic_slash_command.py -v -n 0` — 8/8 pass.
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes.
- `/help` (or its equivalent registry) lists `/diagnostic` with a one-line description.
- `git diff` shows changes only in: `src/probos/experience/shell.py`, `src/probos/experience/panels.py`, the new `commands_diagnostic.py`, and the new test file.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#507](https://github.com/seangalliher/ProbOS/issues/507).
- DECISIONS.md entry stub: AD-700a — `/diagnostic` shell surface for AD-700 LCARS-tier diagnostics; uses module-level `parse_level()`, issues `diagnose_system` intent, renders via new `render_diagnostic_result` panel.

## Revision (2026-05-08)

- **Required #1 applied**: Pinned the canonical Captain-intent dispatch path. D1 step 4 now uses the scout precedent (`commands_knowledge.py:130-148`) — pool lookup (`medical_diagnostician`, verified at `fleet_organization.py:66`), `pool.healthy_agents[0]`, `agent.handle_intent(IntentMessage(...))`. The "Builder verifies the live shape" deferral is removed.
- **Recommended #1 applied**: Test #8 now specifies the exact monkeypatch target (`probos.experience.commands.commands_diagnostic.cmd_diagnostic` — module-level attribute, not the import in shell.py).
- **Recommended #2 applied**: D3 cites `self.COMMANDS` dict-literal at `shell.py:54-110`; gives the exact entry to add.
- **Nit #1 applied**: The `parse_level` correction is now in the Goal section (top-down readers see the right symbol shape immediately).
- **Nit #3 applied**: D1 now lists the `_USAGE` constant explicitly with literal text.
- **Verified Against Codebase** updated: replaced the soft "Builder must read" line with three concrete grep hits (commands_knowledge dispatch shape, fleet_organization pool name, self.COMMANDS registry location).
