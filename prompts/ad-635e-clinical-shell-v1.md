# AD-635e — Clinical Telemetry v5: Shell Command

**Status:** Drafted, awaiting Builder
**Dependencies:** AD-635 v1 (`ClinicalTelemetryService.query_dream_history`, `query_agent_chain_traces`, `audit_log` property; COMPLETE), AD-635b (audit persistence; COMPLETE), AD-635c (`query_circuit_breaker_history`; COMPLETE), AD-635d (REST endpoints; COMPLETE), AD-519 (shell command-module extraction pattern; COMPLETE).
**Estimated tests:** +18 (window [+15, +20])
**Closes:** GH issue #394

## Problem

`src/probos/cognitive/clinical_telemetry.py:65+` ships a complete in-process clinical query facade — three clearance-gated query methods plus an audit-ring snapshot — and AD-635d added the REST surface. The Captain still has no in-shell read path.

The clearance gate at `clinical_telemetry.py:284-313` requires the requester to hold a clinical role (`CLINICAL_ROLES = frozenset({"diagnostician", "counselor"})` at `:57`) AND a qualifying tier (`{FULL, ORACLE}` at `:60-62`). Captain (`agent_id="captain"`) holds neither. Today the Captain cannot read clinical data without impersonating Chapel or Echo via the AD-635d REST `?requester_agent_id=` parameter — fragile, ungrep-able in audit logs, and breaks the principle that the shell IS the Captain interface.

The roadmap entry at `docs/development/roadmap.md:5964` defines AD-635e literally:

> *"Shell command (`/clinical` or `/medbay`) for Captain to query clinical telemetry data directly. Captain bypasses clearance gate (Fleet Admiral authority)."*

## Solution

Five additive changes in four files, plus one new test file:

1. **Service-side captain bypass** (`clinical_telemetry.py`): three `query_*` methods grow ONE keyword-only parameter, `captain_override: bool = False`. When True, the clearance gate is skipped and the audit ring stamps `by_captain=True`. The `_record_audit` helper grows one keyword-only parameter, `by_captain: bool = False`, that controls the optional audit field.
2. **Panel renderers** (`panels.py`): four new functions appended — `render_clinical_dreams_panel`, `render_clinical_traces_panel`, `render_clinical_breakers_panel`, `render_clinical_audit_panel`.
3. **Shell command module** (`commands/commands_clinical.py`, NEW): `cmd_clinical(runtime, console, args)` with five subcommands.
4. **Shell wiring** (`shell.py`): four SEARCH/REPLACE blocks — import tuple, `COMMANDS` dict, `handlers` dict, `_cmd_clinical` proxy.
5. **Tests** (`tests/test_ad635e_clinical_shell_command.py`, NEW): 18 tests across four classes.

No EventTypes added. No mutation of `_authorize_clinical_query`, `CircuitBreakerHistoryStore`, `ClinicalAuditStore`, `CognitiveCircuitBreaker`, `ClinicalTelemetryConfig`, `ProactiveCognitiveLoop`, `routers/clinical.py`, `api.py`, or any startup wiring.

---

## Section 0 — `src/probos/cognitive/clinical_telemetry.py` (4 SEARCH/REPLACE blocks)

### Block 0.1 — `query_dream_history` captain bypass

```
===SEARCH===
    async def query_dream_history(
        self,
        *,
        requester_agent_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent dream reports, most recent first.

        Returns [] (not raises) if requester lacks clearance or if the
        EmergentDetector is unavailable. Every call is logged to the audit ring.
        """
        granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id, "dream_history", granted=False, result_count=0
            )
            logger.warning(
                "AD-635: dream_history denied for %s (clearance/role gate)",
                requester_agent_id,
            )
            return []
===REPLACE===
    async def query_dream_history(
        self,
        *,
        requester_agent_id: str,
        limit: int = 20,
        captain_override: bool = False,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent dream reports, most recent first.

        Returns [] (not raises) if requester lacks clearance or if the
        EmergentDetector is unavailable. Every call is logged to the audit ring.

        AD-635e: when `captain_override=True`, the clearance gate is bypassed
        and the audit-ring entry is stamped `by_captain=True`. This kwarg is
        kwarg-only and not exposed via the AD-635d REST router (callers there
        cannot reach it). Used only by the in-process `/clinical` shell command.
        """
        if captain_override:
            granted = True
        else:
            granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id, "dream_history", granted=False, result_count=0
            )
            logger.warning(
                "AD-635: dream_history denied for %s (clearance/role gate)",
                requester_agent_id,
            )
            return []
===END REPLACE===
```

Then (within the same method) the audit-success call site:

```
===SEARCH===
        self._record_audit(
            requester_agent_id, "dream_history", granted=True, result_count=len(rows)
        )
        return rows

    async def query_agent_chain_traces(
===REPLACE===
        self._record_audit(
            requester_agent_id, "dream_history", granted=True,
            result_count=len(rows), by_captain=captain_override,
        )
        return rows

    async def query_agent_chain_traces(
===END REPLACE===
```

### Block 0.2 — `query_agent_chain_traces` captain bypass

```
===SEARCH===
    async def query_agent_chain_traces(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent chain traces for `target_agent_id`.

        Returns [] (not raises) if requester lacks clearance, if the journal
        is unavailable, or on any underlying failure.
        """
        granted = self._authorize_clinical_query(requester_agent_id)
===REPLACE===
    async def query_agent_chain_traces(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str,
        limit: int = 20,
        captain_override: bool = False,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent chain traces for `target_agent_id`.

        Returns [] (not raises) if requester lacks clearance, if the journal
        is unavailable, or on any underlying failure.

        AD-635e: when `captain_override=True`, the clearance gate is bypassed
        and the audit-ring entry is stamped `by_captain=True` (see
        `query_dream_history` for the policy rationale).
        """
        if captain_override:
            granted = True
        else:
            granted = self._authorize_clinical_query(requester_agent_id)
===END REPLACE===
```

Then the audit-success call site for chain_traces:

```
===SEARCH===
        self._record_audit(
            requester_agent_id,
            "chain_traces",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
        )
        return rows

    @property
    def audit_log(self) -> list[dict[str, Any]]:
===REPLACE===
        self._record_audit(
            requester_agent_id,
            "chain_traces",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
            by_captain=captain_override,
        )
        return rows

    @property
    def audit_log(self) -> list[dict[str, Any]]:
===END REPLACE===
```

### Block 0.3 — `query_circuit_breaker_history` captain bypass

```
===SEARCH===
    async def query_circuit_breaker_history(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """AD-635c: Return up to `limit` recent breaker transitions.

        When `target_agent_id` is provided, filters to that agent.
        When None, returns transitions across all agents (most recent
        first). Returns [] (not raises) if requester lacks clearance,
        if the store is unavailable, or on any underlying failure.
        Every call is logged to the audit ring.
        """
        granted = self._authorize_clinical_query(requester_agent_id)
===REPLACE===
    async def query_circuit_breaker_history(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str | None = None,
        limit: int = 50,
        captain_override: bool = False,
    ) -> list[dict[str, Any]]:
        """AD-635c: Return up to `limit` recent breaker transitions.

        When `target_agent_id` is provided, filters to that agent.
        When None, returns transitions across all agents (most recent
        first). Returns [] (not raises) if requester lacks clearance,
        if the store is unavailable, or on any underlying failure.
        Every call is logged to the audit ring.

        AD-635e: when `captain_override=True`, the clearance gate is bypassed
        and the audit-ring entry is stamped `by_captain=True`.
        """
        if captain_override:
            granted = True
        else:
            granted = self._authorize_clinical_query(requester_agent_id)
===END REPLACE===
```

Then the audit-success call site for circuit_breaker_history:

```
===SEARCH===
        self._record_audit(
            requester_agent_id,
            "circuit_breaker_history",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
        )
        return rows

    # ---- Internals -------------------------------------------------------
===REPLACE===
        self._record_audit(
            requester_agent_id,
            "circuit_breaker_history",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
            by_captain=captain_override,
        )
        return rows

    # ---- Internals -------------------------------------------------------
===END REPLACE===
```

### Block 0.4 — `_record_audit` accepts `by_captain` flag

```
===SEARCH===
    def _record_audit(
        self,
        requester_agent_id: str,
        query_type: str,
        *,
        granted: bool,
        result_count: int,
        target_agent_id: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "requester_agent_id": requester_agent_id,
            "query_type": query_type,
            "granted": bool(granted),
            "result_count": int(result_count),
        }
        if target_agent_id is not None:
            entry["target_agent_id"] = target_agent_id
===REPLACE===
    def _record_audit(
        self,
        requester_agent_id: str,
        query_type: str,
        *,
        granted: bool,
        result_count: int,
        target_agent_id: str | None = None,
        by_captain: bool = False,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "requester_agent_id": requester_agent_id,
            "query_type": query_type,
            "granted": bool(granted),
            "result_count": int(result_count),
        }
        if target_agent_id is not None:
            entry["target_agent_id"] = target_agent_id
        if by_captain:
            entry["by_captain"] = True
===END REPLACE===
```

---

## Section 1 — `src/probos/experience/panels.py` (append 4 new render functions)

Append the following block at the END of the file (after `render_dag_proposal`, the existing last function near `panels.py:1073+`):

```python


# ---------------------------------------------------------------------------
# Clinical telemetry panels (AD-635e)
# ---------------------------------------------------------------------------

def render_clinical_dreams_panel(rows: list[dict[str, Any]]) -> Panel:
    """AD-635e: Render dream-history rows from ClinicalTelemetryService.

    Each row is a dict produced by `EmergentDetector.recent_dreams(limit=...)`.
    Empty list renders an explanatory dim line.
    """
    if not rows:
        return Panel(
            "[dim]No dream cycles recorded.[/dim]",
            title="Clinical: Dreams",
            border_style="magenta",
        )
    table = Table(show_header=True, show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Episodes", justify="right")
    table.add_column("Strengthened", justify="right")
    table.add_column("Pruned", justify="right")
    table.add_column("Trust adj.", justify="right")
    for row in rows:
        ts_raw = row.get("ts") or row.get("timestamp")
        ts = (
            datetime.fromtimestamp(float(ts_raw), tz=timezone.utc).strftime("%H:%M:%S")
            if isinstance(ts_raw, (int, float))
            else "?"
        )
        table.add_row(
            ts,
            str(row.get("episodes_replayed", "-")),
            str(row.get("weights_strengthened", "-")),
            str(row.get("weights_pruned", "-")),
            str(row.get("trust_adjustments", "-")),
        )
    return Panel(table, title="Clinical: Dreams", border_style="magenta")


def render_clinical_traces_panel(
    rows: list[dict[str, Any]], target_agent_id: str
) -> Panel:
    """AD-635e: Render cognitive-chain-trace rows for one target agent."""
    if not rows:
        return Panel(
            f"[dim]No chain traces for {target_agent_id}.[/dim]",
            title=f"Clinical: Chain Traces ({target_agent_id})",
            border_style="cyan",
        )
    table = Table(show_header=True, show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Chain", max_width=20)
    table.add_column("Outcome")
    table.add_column("Steps", justify="right")
    for row in rows:
        ts_raw = row.get("ts") or row.get("timestamp")
        ts = (
            datetime.fromtimestamp(float(ts_raw), tz=timezone.utc).strftime("%H:%M:%S")
            if isinstance(ts_raw, (int, float))
            else "?"
        )
        chain = str(row.get("chain_id") or row.get("trace_id") or "?")[:20]
        outcome = str(row.get("outcome") or row.get("status") or "-")
        steps = row.get("step_count") or len(row.get("steps") or []) or "-"
        table.add_row(ts, chain, outcome, str(steps))
    return Panel(
        table,
        title=f"Clinical: Chain Traces ({target_agent_id})",
        border_style="cyan",
    )


def render_clinical_breakers_panel(
    rows: list[dict[str, Any]], target_agent_id: str | None
) -> Panel:
    """AD-635e: Render circuit-breaker history rows.

    `target_agent_id=None` indicates fleet-wide query.
    """
    label = target_agent_id or "fleet-wide"
    if not rows:
        return Panel(
            f"[dim]No breaker transitions ({label}).[/dim]",
            title=f"Clinical: Circuit Breakers ({label})",
            border_style="yellow",
        )
    table = Table(show_header=True, show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Agent")
    table.add_column("State")
    table.add_column("Zone")
    table.add_column("Reason", max_width=30)
    for row in rows:
        ts_raw = row.get("ts") or row.get("timestamp")
        ts = (
            datetime.fromtimestamp(float(ts_raw), tz=timezone.utc).strftime("%H:%M:%S")
            if isinstance(ts_raw, (int, float))
            else "?"
        )
        table.add_row(
            ts,
            str(row.get("agent_id", "-")),
            str(row.get("state", "-")),
            str(row.get("zone", "-")),
            str(row.get("reason", ""))[:30],
        )
    return Panel(
        table,
        title=f"Clinical: Circuit Breakers ({label})",
        border_style="yellow",
    )


def render_clinical_audit_panel(rows: list[dict[str, Any]]) -> Panel:
    """AD-635e: Render audit-ring snapshot."""
    if not rows:
        return Panel(
            "[dim]Audit ring is empty.[/dim]",
            title="Clinical: Audit",
            border_style="cyan",
        )
    table = Table(show_header=True, show_lines=False)
    table.add_column("Time", style="dim")
    table.add_column("Requester")
    table.add_column("Query")
    table.add_column("Granted", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("By Captain", justify="right")
    for row in rows:
        ts_raw = row.get("ts")
        ts = (
            datetime.fromtimestamp(float(ts_raw), tz=timezone.utc).strftime("%H:%M:%S")
            if isinstance(ts_raw, (int, float))
            else "?"
        )
        granted = "[green]yes[/green]" if row.get("granted") else "[red]no[/red]"
        by_cap = "[bold]yes[/bold]" if row.get("by_captain") else "-"
        table.add_row(
            ts,
            str(row.get("requester_agent_id", "-")),
            str(row.get("query_type", "-")),
            granted,
            str(row.get("result_count", "-")),
            by_cap,
        )
    return Panel(table, title="Clinical: Audit", border_style="cyan")
```

---

## Section 2 — `src/probos/experience/commands/commands_clinical.py` (NEW file)

Create the file with this exact content:

```python
"""Clinical telemetry shell command for ProbOSShell (AD-635e).

`/clinical` surfaces the AD-635 / AD-635b / AD-635c / AD-635d clinical data
domains directly in the Captain's shell. Captain bypasses the clearance gate
via `captain_override=True`; every query is stamped `by_captain=True` on the
service's in-memory audit ring (and persisted via AD-635b when configured).

Subcommands:
  /clinical                       Help / overview
  /clinical dreams [N]            Recent dream-cycle reports (default 20)
  /clinical traces <id> [N]       Recent cognitive-chain traces for one agent
  /clinical breakers [<id>] [N]   Circuit-breaker history (per-agent or fleet)
  /clinical audit [N]             Service audit-ring snapshot (default 200)

When `runtime.clinical_telemetry is None` (the default `enabled=False`
config), prints an explanatory message and returns. Mirrors `cmd_dream`
behavior for the analogous `dream_scheduler is None` case.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console

from probos.experience import panels

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

# AD-635e DLog #12 — canonical Captain identity (matches ward_room_router.py:325,
# clearance_grants.py:111, acm.py:250).
_CAPTAIN_ID = "captain"

_USAGE = (
    "[bold]/clinical[/bold] — clinical telemetry (Captain authority)\n\n"
    "  /clinical dreams [N]            Recent dream-cycle reports\n"
    "  /clinical traces <agent> [N]    Recent chain traces for one agent\n"
    "  /clinical breakers [<agent>] [N]  Circuit-breaker history\n"
    "  /clinical audit [N]             Audit-ring snapshot\n"
)


def _parse_limit(token: str, default: int) -> int | None:
    """Parse a positional integer arg. Returns None on malformed input."""
    if not token:
        return default
    try:
        n = int(token)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else default


async def cmd_clinical(
    runtime: "ProbOSRuntime", console: Console, args: str
) -> None:
    """Handle `/clinical [subcommand] [args...]`."""
    service = getattr(runtime, "clinical_telemetry", None)
    if service is None:
        console.print(
            "[yellow]Clinical telemetry is not enabled. "
            "Set `clinical_telemetry.enabled: true` in config to activate.[/yellow]"
        )
        return

    parts = args.split()
    if not parts:
        console.print(_USAGE)
        return

    sub = parts[0].lower()
    rest = parts[1:]

    if sub == "dreams":
        await _sub_dreams(service, console, rest)
    elif sub == "traces":
        await _sub_traces(service, console, rest)
    elif sub == "breakers":
        await _sub_breakers(service, console, rest)
    elif sub == "audit":
        await _sub_audit(service, console, rest)
    else:
        console.print(f"[red]Unknown subcommand: {sub}[/red]")
        console.print(_USAGE)


async def _sub_dreams(service, console: Console, rest: list[str]) -> None:
    limit_token = rest[0] if rest else ""
    limit = _parse_limit(limit_token, default=20)
    if limit is None:
        console.print(f"[red]Usage: /clinical dreams [N]; got '{limit_token}'.[/red]")
        return
    rows = await service.query_dream_history(
        requester_agent_id=_CAPTAIN_ID,
        limit=limit,
        captain_override=True,
    )
    console.print(panels.render_clinical_dreams_panel(rows))


async def _sub_traces(service, console: Console, rest: list[str]) -> None:
    if not rest:
        console.print("[yellow]Usage: /clinical traces <agent_id> [N][/yellow]")
        return
    target = rest[0]
    limit_token = rest[1] if len(rest) > 1 else ""
    limit = _parse_limit(limit_token, default=20)
    if limit is None:
        console.print(
            f"[red]Usage: /clinical traces <agent_id> [N]; got '{limit_token}'.[/red]"
        )
        return
    rows = await service.query_agent_chain_traces(
        requester_agent_id=_CAPTAIN_ID,
        target_agent_id=target,
        limit=limit,
        captain_override=True,
    )
    console.print(panels.render_clinical_traces_panel(rows, target_agent_id=target))


async def _sub_breakers(service, console: Console, rest: list[str]) -> None:
    target: str | None = None
    limit_token = ""
    if rest:
        # First token is either an agent_id or a numeric limit (fleet-wide).
        if rest[0].lstrip("-").isdigit():
            limit_token = rest[0]
        else:
            target = rest[0]
            if len(rest) > 1:
                limit_token = rest[1]
    limit = _parse_limit(limit_token, default=50)
    if limit is None:
        console.print(
            f"[red]Usage: /clinical breakers [<agent_id>] [N]; got '{limit_token}'.[/red]"
        )
        return
    rows = await service.query_circuit_breaker_history(
        requester_agent_id=_CAPTAIN_ID,
        target_agent_id=target,
        limit=limit,
        captain_override=True,
    )
    console.print(
        panels.render_clinical_breakers_panel(rows, target_agent_id=target)
    )


async def _sub_audit(service, console: Console, rest: list[str]) -> None:
    limit_token = rest[0] if rest else ""
    limit = _parse_limit(limit_token, default=200)
    if limit is None:
        console.print(f"[red]Usage: /clinical audit [N]; got '{limit_token}'.[/red]")
        return
    # AD-635e DLog #10: audit_log is a public no-gate property; slice in-shell.
    snapshot = service.audit_log
    rows = list(snapshot[-limit:]) if limit > 0 else []
    console.print(panels.render_clinical_audit_panel(rows))
```

---

## Section 3 — `src/probos/experience/shell.py` (4 SEARCH/REPLACE blocks)

### Block 3.1 — Add `commands_clinical` to import tuple

```
===SEARCH===
from probos.experience.commands import (
    commands_status,
    commands_plan,
    commands_directives,
    commands_procedure,
    commands_gap,
    commands_qualification,
    commands_autonomous,
    commands_memory,
    commands_knowledge,
    commands_llm,
    commands_introspection,
    commands_alert,
    commands_clearance,
    commands_config,
    commands_tool_access,
    commands_skill,
    commands_manifest,
)
===REPLACE===
from probos.experience.commands import (
    commands_status,
    commands_plan,
    commands_directives,
    commands_procedure,
    commands_gap,
    commands_qualification,
    commands_autonomous,
    commands_memory,
    commands_knowledge,
    commands_llm,
    commands_introspection,
    commands_alert,
    commands_clearance,
    commands_clinical,
    commands_config,
    commands_tool_access,
    commands_skill,
    commands_manifest,
)
===END REPLACE===
```

### Block 3.2 — Register `/clinical` in `COMMANDS` dict

```
===SEARCH===
        "/grant":     "Manage clearance grants (issue/revoke/list)",
        "/tool-access": "Manage tool permissions (grant/restrict/revoke/break-lock/list/check)",
        "/skill":     "Manage cognitive skills (list/discover/import/info/enrich/remove)",
        "/debug":     "Toggle debug mode (/debug on|off)",
===REPLACE===
        "/grant":     "Manage clearance grants (issue/revoke/list)",
        "/tool-access": "Manage tool permissions (grant/restrict/revoke/break-lock/list/check)",
        "/skill":     "Manage cognitive skills (list/discover/import/info/enrich/remove)",
        "/clinical":  "Clinical telemetry (dreams/traces/breakers/audit) — Captain authority",
        "/debug":     "Toggle debug mode (/debug on|off)",
===END REPLACE===
```

### Block 3.3 — Register `/clinical` handler

```
===SEARCH===
            "/alert":      lambda: commands_alert.cmd_alert(rt, con, arg),
            "/grant":      lambda: commands_clearance.cmd_grant(rt, con, arg),
            "/tool-access": lambda: commands_tool_access.cmd_tool_access(rt, con, arg),
            "/skill":      lambda: commands_skill.cmd_skill(rt, con, arg),

            "/config":     lambda: commands_config.cmd_config(rt, con, arg),
===REPLACE===
            "/alert":      lambda: commands_alert.cmd_alert(rt, con, arg),
            "/grant":      lambda: commands_clearance.cmd_grant(rt, con, arg),
            "/tool-access": lambda: commands_tool_access.cmd_tool_access(rt, con, arg),
            "/skill":      lambda: commands_skill.cmd_skill(rt, con, arg),
            "/clinical":   lambda: commands_clinical.cmd_clinical(rt, con, arg),

            "/config":     lambda: commands_config.cmd_config(rt, con, arg),
===END REPLACE===
```

### Block 3.4 — Add `_cmd_clinical` backward-compat proxy

Append after the existing `_cmd_cache` proxy in the AD-519 proxy block (i.e., after `await commands_introspection.cmd_cache(...)` at `shell.py:506-507`, before `_cmd_explain` at `:509`):

```
===SEARCH===
    async def _cmd_cache(self, arg: str) -> None:
        await commands_introspection.cmd_cache(self.runtime, self.console, arg)

    async def _cmd_explain(self, arg: str) -> None:
        await self._handle_nl("what just happened?")
===REPLACE===
    async def _cmd_cache(self, arg: str) -> None:
        await commands_introspection.cmd_cache(self.runtime, self.console, arg)

    async def _cmd_clinical(self, arg: str) -> None:
        await commands_clinical.cmd_clinical(self.runtime, self.console, arg)

    async def _cmd_explain(self, arg: str) -> None:
        await self._handle_nl("what just happened?")
===END REPLACE===
```

---

## Section 4 — `tests/test_ad635e_clinical_shell_command.py` (NEW file)

Create the file. Test harness mirrors `tests/test_commands_memory.py` (`MagicMock(spec=ProbOSRuntime)`, `Console(file=StringIO(), ...)`).

The 18 tests, in four classes:

**`TestServiceCaptainOverride`** — locks the service-side bypass + audit field (6 tests).

1. `test_query_dream_history_captain_override_bypasses_gate` — service constructed with a runtime where `_resolve_agent_type("captain")` returns `""` (Captain isn't in CLINICAL_ROLES). Call `query_dream_history(requester_agent_id="captain", captain_override=True)`. Assert: result is the rows from a stubbed `_emergent_detector.recent_dreams` (NOT `[]`). Assert: `service.audit_log[-1]["granted"] is True`.
2. `test_query_dream_history_captain_override_audits_by_captain` — same setup. After call, assert: `service.audit_log[-1]["by_captain"] is True`.
3. `test_query_dream_history_default_no_by_captain_field` — call with `captain_override=False` (default). Assert `"by_captain" not in service.audit_log[-1]` (additive-field contract from DLog #4).
4. `test_query_agent_chain_traces_captain_override_bypasses_gate` — analogous to #1 but for chain traces. Stub `cognitive_journal.get_recent_chain_traces` (`AsyncMock`). Assert non-empty result + `granted=True`.
5. `test_query_agent_chain_traces_captain_override_audits_by_captain` — assert `audit_log[-1]["by_captain"] is True`.
6. `test_query_circuit_breaker_history_captain_override_bypasses_gate` — analogous to #1 but for breaker history. Stub the service's internal `_circuit_breaker_history_store.recent` (`AsyncMock`). Assert non-empty + `granted=True` + `by_captain=True`.

**`TestShellRegistration`** — locks the wiring (3 tests).

7. `test_clinical_command_in_COMMANDS` — `from probos.experience.shell import ProbOSShell; assert "/clinical" in ProbOSShell.COMMANDS`.
8. `test_clinical_command_help_text_mentions_captain_authority` — `assert "Captain" in ProbOSShell.COMMANDS["/clinical"]`.
9. `test_cmd_clinical_proxy_exists` — `assert hasattr(ProbOSShell, "_cmd_clinical") and callable(ProbOSShell._cmd_clinical)`.

**`TestCmdClinicalDispatch`** — locks the command-level dispatch (5 tests).

10. `test_service_disabled_prints_message` — `runtime.clinical_telemetry = None`. Call `cmd_clinical(runtime, console, "")`. Assert output contains "not enabled" (case-insensitive).
11. `test_no_args_prints_usage` — service is a `MagicMock`; call with `args=""`. Assert output contains `"/clinical dreams"` AND `"/clinical traces"`.
12. `test_unknown_subcommand_prints_error` — call with `args="frobulate"`. Assert output contains "Unknown subcommand: frobulate" AND the usage block.
13. `test_dreams_invalid_limit_prints_usage_error` — service is a `MagicMock`; call with `args="dreams notanumber"`. Assert output contains "Usage" AND `'notanumber'`.
14. `test_traces_missing_agent_id_prints_usage_error` — call with `args="traces"`. Assert output contains "Usage: /clinical traces <agent_id>".

**`TestCmdClinicalQueries`** — locks the per-subcommand happy paths and panel emission (4 tests).

15. `test_dreams_calls_service_with_captain_override` — stub `service.query_dream_history` as `AsyncMock(return_value=[{"ts": 1.0, "episodes_replayed": 5}])`. Call `cmd_clinical(rt, con, "dreams 7")`. Assert `service.query_dream_history.await_args.kwargs == {"requester_agent_id": "captain", "limit": 7, "captain_override": True}`.
16. `test_traces_calls_service_per_agent` — stub `service.query_agent_chain_traces`. Call `cmd_clinical(rt, con, "traces alice 5")`. Assert kwargs include `requester_agent_id="captain"`, `target_agent_id="alice"`, `limit=5`, `captain_override=True`.
17. `test_breakers_no_agent_id_calls_fleet_wide` — stub `service.query_circuit_breaker_history`. Call `cmd_clinical(rt, con, "breakers")`. Assert kwargs include `target_agent_id=None`, `captain_override=True`. (Locks DLog #7.)
18. `test_audit_uses_audit_log_property_with_slice` — give the service a fake `audit_log` PropertyMock returning a list of 5 entries. Call `cmd_clinical(rt, con, "audit 2")`. Assert the rendered panel ONLY contains the last 2 entries (verify by checking the output includes the last entry's `requester_agent_id` value but not the first entry's). (Locks DLog #10.)

Use `Console(file=StringIO(), force_terminal=True, width=120)` and a `get_output(console)` helper (mirrors `test_commands_memory.py:18-22`). All async tests use `@pytest.mark.asyncio`.

---

## What This Does NOT Change

- `_authorize_clinical_query` — not modified. The Captain bypass is a sibling fast-path branch on the call site, not a gate edit.
- `routers/clinical.py` — not modified. REST callers cannot reach `captain_override` (kwarg-only with default; not forwarded by the router).
- `api.py` — not modified.
- `startup/finalize.py` — not modified.
- `ClinicalTelemetryConfig` — not modified.
- `CircuitBreakerHistoryStore`, `ClinicalAuditStore` — not modified (the audit field is added at the in-memory dict construction site; persistence layer accepts the entry as opaque dict).
- HXI / TypeScript — not modified (HXI clinical panel is a follow-up AD).
- Existing AD-635 / AD-635b / AD-635c / AD-635d tests — must continue to pass without modification.

---

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635e v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635d). |
| `docs/development/roadmap.md:5964` | Flip `*(Scoped, OSS, Issue #394)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook shell-command sibling pattern; `commands_clinical.py` mirrors `commands_memory.py` shape). |
| `prompts/wave-plan.yaml` (id: 65) | Set `status: done` post-archive. |
| GH issue #394 | Closed by Captain post-merge with commit hash. |

---

## Acceptance Criteria

1. Test count moves from 11368 to a value in [11383, 11388]; target 11386 (+18).
2. All 18 new tests pass.
3. Existing AD-635 / AD-635b / AD-635c / AD-635d tests pass without modification (`pytest tests/test_ad635*.py -n 0`).
4. `python -c "from probos.experience.shell import ProbOSShell; assert '/clinical' in ProbOSShell.COMMANDS"` exits 0.
5. `python -c "from probos.experience.commands import commands_clinical; assert callable(commands_clinical.cmd_clinical)"` exits 0.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (HEAD `3738f2e`, 2026-05-05)

| Claim | Verifying grep |
|---|---|
| `ClinicalTelemetryService` at `clinical_telemetry.py:65` | `Select-String -Pattern "^class ClinicalTelemetryService" src/probos/cognitive/clinical_telemetry.py` → line 65 |
| `query_dream_history` signature at `:93` | `Select-String -Pattern "async def query_dream_history" src/probos/cognitive/clinical_telemetry.py` → line 93 |
| `query_agent_chain_traces` signature at `:139` | `Select-String -Pattern "async def query_agent_chain_traces" src/probos/cognitive/clinical_telemetry.py` → line 139 |
| `audit_log` property at `:206-208` | `Select-String -Pattern "def audit_log" src/probos/cognitive/clinical_telemetry.py` → line 207 (decorator at 206) |
| `query_circuit_breaker_history` signature at `:211` | `Select-String -Pattern "async def query_circuit_breaker_history" src/probos/cognitive/clinical_telemetry.py` → line 211 |
| `_authorize_clinical_query` at `:284` | `Select-String -Pattern "def _authorize_clinical_query" src/probos/cognitive/clinical_telemetry.py` → line 284 |
| `_record_audit` at `:340` | `Select-String -Pattern "def _record_audit" src/probos/cognitive/clinical_telemetry.py` → line 340 |
| `CLINICAL_ROLES` at `:57` excludes "captain" | `Select-String -Pattern "CLINICAL_ROLES" src/probos/cognitive/clinical_telemetry.py` → `frozenset({"diagnostician", "counselor"})` |
| Canonical `"captain"` identifier | `ward_room_router.py:325`, `clearance_grants.py:111`, `acm.py:250` (3 confirming sites) |
| `ProbOSShell.COMMANDS` dict at `shell.py:52` | `Select-String -Pattern "COMMANDS: dict" src/probos/experience/shell.py` → line 52 |
| Import tuple at `shell.py:11-29` | `Select-String -Pattern "from probos.experience.commands import" src/probos/experience/shell.py` → lines 11 (open) and 29 (close) |
| `handlers` dict in `_dispatch_slash` at `shell.py:228` | `Select-String -Pattern "handlers: dict" src/probos/experience/shell.py` → line 228 |
| `_cmd_cache` / `_cmd_explain` proxies | `Select-String -Pattern "async def _cmd_cache\|async def _cmd_explain" src/probos/experience/shell.py` → lines 506, 509 |
| `panels.render_dream_panel` reference shape at `:690` | `Select-String -Pattern "^def render_dream_panel" src/probos/experience/panels.py` → line 690 |
| `commands_memory.cmd_dream` reference shape at `:84` | `Select-String -Pattern "^async def cmd_dream" src/probos/experience/commands/commands_memory.py` → line 84 |
| `routers/clinical.py:69-73` does not pass `captain_override` | (read above) — only forwards `requester_agent_id`, `limit` |
| `tests/test_commands_memory.py:25-34` mock-runtime fixture pattern | (read above) — `MagicMock(spec=ProbOSRuntime)` with attribute-level stubs |
| Baseline 11368 at HEAD `3738f2e` | `pytest tests/ --collect-only -q -n 0` → "11368 tests collected in 5.39s" |
| Highest AD = AD-695 (AD-635e is unique) | `Select-String -Pattern "^### AD-69" decisions-era-4-evolution.md` |
