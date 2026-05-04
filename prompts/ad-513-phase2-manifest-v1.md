# AD-513 Phase 2 v1: Crew Manifest Shell Command + Watch Filter + Ship Manifest

**Status:** Drafted (Wave 17)
**Risk:** low (additive shell command + read-only ontology helpers)
**Depends on:** AD-513 Phase 1 (shipped — `get_crew_manifest()` at ontology/service.py:469)
**Closes:** GitHub issue #14

---

## Solution Overview

AD-513 Phase 1 (shipped) delivered `get_crew_manifest()` + HXI CrewRosterPanel + REST endpoint. Phase 2 has 6 capabilities listed in roadmap.md (line 6398): **(a)** shell command, **(b)** trust-gated visibility, **(c)** agent tool access, **(d)** watch filter, **(e)** ACM lifecycle state + competency fields, **(f)** ship manifest for federation.

**v1 ships 3 of 6 capabilities** (per convention #14 aggressive pre-deferral) — the lowest-risk additive surfaces:

1. **(a) Shell command `/manifest`** — formatted Rich table with department/watch filter args. Mirrors existing `/agents` shell command pattern (commands_status.cmd_agents).
2. **(d) Watch filter** — extend `get_crew_manifest()` with `watch: str | None = None` kwarg. Filters by `WatchManager` assignment. Read-only consumer; no schema migration.
3. **(f) Ship manifest** — new `get_ship_manifest()` method on `VesselOntologyService`. Returns vessel-level summary dict (ship_name, agent_count, departments, watches, alert_state) for gossip/workforce planning.

**Deferred:**

- AD-513 Phase 2b: Trust-gated visibility — redacted view based on viewer's earned-agency tier. Requires viewer-context plumbing through API/shell. Forcing function: a real consumer needs gated access.
- AD-513 Phase 2c: Agent tool access — internal-API exposure for agents to query manifest themselves. Requires Tool registry integration. Forcing function: an agent (e.g., Security Chief) makes the request via a designed agent, not slash command.
- AD-513 Phase 2e: ACM lifecycle state + competency fields — extension of manifest payload. Requires ACM lifecycle-state read API (verify it exists) + competency aggregation from skill_framework. Forcing function: HXI panel or shell consumer needs the fields displayed.

## Dependencies

- `runtime.ontology` — read-only consumer (`get_crew_manifest()` at service.py:469). Verified at cognitive_agent.py:231, proactive.py:2368, routers/agents.py:108. Real attribute name is `runtime.ontology` (NOT `runtime.vessel_ontology`).
- `runtime.watch_manager` — read-only consumer (verify attribute name + `get_assignment_for_agent` or equivalent watch query API).
- `runtime.trust_network` — read-only consumer (existing optional enrichment in get_crew_manifest).
- `runtime.callsign_registry` — read-only consumer (existing optional enrichment).
- `src/probos/experience/shell.py:218-298` — slash command dispatch table (extend with `/manifest`).
- `src/probos/experience/commands/commands_status.py` (or new `commands_manifest.py`) — handler module pattern verified.

All reads from existing surfaces; no writes.

## Sections

### Section 0 — EventTypes

No new EventTypes in v1. `/manifest` is observational; no state mutation. Phase 2c (agent tool access) may introduce events; deferred.

### Section 1 — Extend `VesselOntologyService.get_crew_manifest()` with watch filter

In `src/probos/ontology/service.py:469`:

```python
def get_crew_manifest(
    self,
    *,
    department: str | None = None,
    watch: str | None = None,  # NEW: AD-513 Phase 2 capability (d)
    trust_network: Any | None = None,
    callsign_registry: Any | None = None,
    watch_manager: Any | None = None,  # NEW: optional dep injection for watch enrichment
) -> list[dict[str, Any]]:
```

Behavior change:
- If `watch_manager` provided AND `watch` is set: filter manifest entries to only those with `watch_assignment == watch`.
- If `watch_manager` provided (regardless of `watch` filter): enrich entry with `watch` field.
- Backward-compat: existing callers pass nothing, get current behavior.

### Section 2 — Add `VesselOntologyService.get_ship_manifest()`

New method:

```python
def get_ship_manifest(
    self,
    *,
    trust_network: Any | None = None,
    watch_manager: Any | None = None,
    alert_manager: Any | None = None,
) -> dict[str, Any]:
    """Vessel-level summary for federation gossip / workforce planning.

    Returns:
        {
            "ship_name": str,
            "vessel_class": str,
            "agent_count": int,
            "departments": list[str],
            "watches": list[str] (active watch names; empty if watch_manager None),
            "alert_state": str (current alert; "GREEN" if alert_manager None),
            "manifest_summary": [{"agent_type", "callsign", "department", "post"}, ...],
        }

    All enrichment params optional. Designed for cheap-to-compute vessel-level overview
    for gossip subsystems.
    """
```

### Section 3 — Add `/manifest` shell command

New file: `src/probos/experience/commands/commands_manifest.py`:

```python
"""Crew Manifest shell command (AD-513 Phase 2)."""
from __future__ import annotations
from typing import Any

from rich.console import Console
from rich.table import Table


async def cmd_manifest(runtime: Any, console: Console, arg: str) -> None:
    """Print formatted crew manifest.

    Usage:
        /manifest                  — full ship roster
        /manifest <department>     — department filter
        /manifest watch:<watch>    — watch filter
        /manifest <dept> watch:<w> — combined
        /manifest --ship           — ship-level summary (single row)
    """
    ontology = getattr(runtime, "ontology", None)
    if not ontology:
        console.print("[red]No ontology service available[/red]")
        return

    department = None
    watch = None
    show_ship = False
    for token in arg.split():
        if token == "--ship":
            show_ship = True
        elif token.startswith("watch:"):
            watch = token.split(":", 1)[1]
        elif not department:
            department = token

    if show_ship:
        summary = ontology.get_ship_manifest(
            trust_network=getattr(runtime, "trust_network", None),
            watch_manager=getattr(runtime, "watch_manager", None),
            alert_manager=getattr(runtime, "alert_manager", None),
        )
        # Render as 2-col key-value Rich table
        ...
        return

    manifest = ontology.get_crew_manifest(
        department=department,
        watch=watch,
        trust_network=getattr(runtime, "trust_network", None),
        callsign_registry=getattr(runtime, "callsign_registry", None),
        watch_manager=getattr(runtime, "watch_manager", None),
    )
    if not manifest:
        console.print("[yellow]No crew matched[/yellow]")
        return

    table = Table(title="Ship's Crew Manifest")
    for col in ("Callsign", "Department", "Post", "Rank", "Trust", "Watch"):
        table.add_column(col)
    for entry in manifest:
        table.add_row(
            str(entry.get("callsign", "")),
            str(entry.get("department", "")),
            str(entry.get("post", "")),
            str(entry.get("rank", "")),
            f"{entry.get('trust_score', 0.0):.2f}",
            str(entry.get("watch", "")),
        )
    console.print(table)
```

### Section 4 — Wire `/manifest` into shell dispatch

In `src/probos/experience/shell.py:218-298` dispatch table, add:
```python
from probos.experience.commands import commands_manifest
# ... in handlers dict (group with /agents and other status commands):
"/manifest":   lambda: commands_manifest.cmd_manifest(rt, con, arg),
```

Update `self.COMMANDS` (used by `/help`) to include `/manifest` with usage one-liner.

### Section 5 — Pydantic config (optional)

No new config required. Manifest is read-only; existing ontology + watch_manager surfaces.

## What This Does NOT Change

- AD-513 Phase 2b/c/e — deferred (trust-gated visibility, agent tool access, ACM lifecycle/competency fields).
- HXI CrewRosterPanel — unchanged. Phase 1 delivery untouched.
- REST endpoint `GET /api/ontology/crew-manifest` — unchanged. Watch filter could be added later; v1 ships shell + ship-manifest only.
- Federation gossip integration — `get_ship_manifest()` is the surface; actual gossip wiring is AD-479 territory.
- TrustNetwork / CallsignRegistry / WatchManager APIs — read-only consumers; no modifications.
- `_build_crew_complement` anti-confabulation block in CognitiveAgent — Phase 1 surface untouched.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_get_crew_manifest_watch_filter_returns_matching_only` | Section 1 watch filter behavior |
| 2 | `test_get_crew_manifest_watch_filter_empty_when_no_match` | Edge case |
| 3 | `test_get_crew_manifest_no_watch_filter_preserves_existing_behavior` | Backward compat |
| 4 | `test_get_crew_manifest_enriches_watch_field_when_watch_manager_provided` | Enrichment behavior |
| 5 | `test_get_crew_manifest_skips_watch_when_watch_manager_none` | Optional dep |
| 6 | `test_get_ship_manifest_returns_vessel_level_summary` | Section 2 happy path |
| 7 | `test_get_ship_manifest_with_no_enrichment_returns_minimal_summary` | Optional deps |
| 8 | `test_get_ship_manifest_includes_active_watches_when_watch_manager_present` | Watches population |
| 9 | `test_get_ship_manifest_alert_state_defaults_to_green_when_alert_manager_none` | Default behavior |
| 10 | `test_cmd_manifest_no_args_prints_table` | Shell command happy path |
| 11 | `test_cmd_manifest_with_department_filter` | Section 3 dept arg |
| 12 | `test_cmd_manifest_with_watch_filter` | Section 3 watch:X arg |
| 13 | `test_cmd_manifest_with_ship_flag_prints_summary` | Section 3 --ship |
| 14 | `test_cmd_manifest_no_ontology_prints_error` | Error path |
| 15 | `test_cmd_manifest_empty_match_prints_yellow_warning` | Empty result behavior |
| 16 | `test_shell_dispatch_routes_manifest_to_handler` | Section 4 wiring |
| 17 | `test_shell_help_includes_manifest_command` | Section 4 COMMANDS update |

Total: ~17 tests at `tests/test_ad513_phase2_manifest.py`.

## Tracking

1. **PROGRESS.md:** prepend AD-513 Phase 2 v1 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-513 Phase 2 v1: Crew Manifest Shell + Watch Filter + Ship Manifest (2026-05-03)

**Problem:** AD-513 Phase 1 delivered `get_crew_manifest()` + HXI panel + REST endpoint. Phase 2 has 6 follow-up capabilities (a-f). Trust-gated visibility, agent tool access, and ACM/competency fields each require new infrastructure. Shell command + watch filter + ship-summary are read-only additive surfaces shippable independently.

**Decision:** v1 ships 3 of 6 Phase-2 capabilities:
- (a) `/manifest` shell command — formatted Rich table with department/watch filters and `--ship` flag for vessel-level summary.
- (d) Watch filter on `get_crew_manifest(watch=...)` — additive kwarg + watch_manager dep injection. Backward-compatible.
- (f) `get_ship_manifest()` — vessel-level summary (ship_name, agent_count, departments, watches, alert_state) for federation gossip / workforce planning.

All read-only consumers; no writes; no schema migration.

**Why:** Wave 5 convention #14 aggressive pre-deferral. Phase 2b/c/e each have meaningful infrastructure asks (viewer-context plumbing, Tool registry integration, ACM lifecycle API). Shell + watch + ship-summary deliver immediate Captain-facing value with minimal coupling.

**Deferred:**
- AD-513 Phase 2b: Trust-gated visibility (redacted views by earned-agency tier).
- AD-513 Phase 2c: Agent tool access (internal API for designed agents).
- AD-513 Phase 2e: ACM lifecycle state + competency fields in manifest payload.

**Cross-links:** AD-513 Phase 1 (ontology/service.py:469), AD-429 (Ontology), AD-064 (Watch Rotation — WatchManager consumer), AD-479 (Federation — ship manifest is the gossip surface).
```

3. **docs/development/roadmap.md:** flip AD-513 Phase 2 status to `partial — v1 ships /manifest shell + watch filter + ship-summary; trust-gated visibility / agent tool access / ACM-competency fields deferred to Phase 2b/c/e`.

## Verified Against Codebase (2026-05-03)

```
grep -n "class VesselOntologyService\|def get_crew_manifest" src/probos/ontology/service.py
   45: class VesselOntologyService:
  469: def get_crew_manifest(self, *, department, trust_network, callsign_registry)

grep -n "_dispatch_slash\|/agents\|handler = handlers.get" src/probos/experience/shell.py
  218: async def _dispatch_slash(self, line: str) -> None:
  226: handlers: dict[str, Any] = {
  228: "/agents": lambda: commands_status.cmd_agents(rt, con, arg),
  293: handler = handlers.get(cmd)

grep -rn "class WatchManager\|self.watch_manager\|runtime.watch_manager" src/probos/ | head -3
  (Builder verifies at build time — runtime attribute name)

grep -rn "class CallsignRegistry\|self.callsign_registry" src/probos/ | head -3
  (Builder verifies)
```

## Acceptance Criteria

- `get_crew_manifest(watch=..., watch_manager=...)` extended (backward-compatible).
- `get_ship_manifest()` shipped on VesselOntologyService.
- `/manifest` slash command in shell with department/watch/--ship args.
- `commands_manifest.py` module added.
- Shell dispatch table + COMMANDS include `/manifest`.
- 17 tests pass.
- DECISIONS.md entry under Era V.
- GH issue #14 closes when commit lands.

## Hard-Stops

- `runtime.watch_manager` attribute doesn't exist with assumed API — surface; may need different consumer pattern.
- `runtime.callsign_registry` differs from Phase 1 enrichment pattern — surface; backward-compat must hold.
- Existing `/manifest` command name collides with another module — verify by grep before implementing.
- AD-513 Phase 2b/c/e scope creep — if you find yourself adding viewer-context plumbing or Tool registry integration, STOP.
- WatchManager doesn't expose query-by-watch API — surface; v1 may need to fall back to per-agent iteration.
