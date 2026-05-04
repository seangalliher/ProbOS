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

Behavior:

1. **Build agent_id -> watch lookup once.** `WatchManager` exposes no per-agent query API; reverse `get_roster()` (verified at watch_rotation.py:150-152, returns `{watch_name: [agent_id, ...]}`):

   ```python
   agent_to_watch: dict[str, str] = {}
   if watch_manager is not None:
       for watch_name, agent_ids in watch_manager.get_roster().items():
           for aid in agent_ids:
               agent_to_watch[aid] = watch_name  # WatchType.value already lowercase
   ```

2. **Match key.** WatchManager keys by `agent_id` (assign_to_watch signature, watch_rotation.py:136). Manifest entries carry `agent_id` (may be empty string when crew is unfilled, per service.py:497-503). Skip enrichment for empty `agent_id`:

   ```python
   aid = entry.get("agent_id") or ""
   entry_watch = agent_to_watch.get(aid) if aid else None
   if watch_manager is not None:
       entry["watch"] = entry_watch or ""
   ```

3. **Watch filter.** If `watch` is set, normalize to lowercase to match `WatchType.value` (watch_rotation.py:22, `ALPHA = "alpha"`), then drop entries whose `entry_watch` doesn't match:

   ```python
   if watch is not None:
       watch_normalized = watch.lower()
       filtered = [e for e in filtered if agent_to_watch.get(e.get("agent_id") or "") == watch_normalized]
   ```

   If `watch` is set but `watch_manager` is None, return empty list (cannot satisfy filter).

4. **Backward-compat.** Existing callers (cognitive_agent.py:4126, routers/ontology.py:64) pass neither `watch` nor `watch_manager`; behavior unchanged.

### Section 2 — Add `VesselOntologyService.get_ship_manifest()`

New method. **Sources** (verified):

- `ship_name` — `self.get_vessel_identity().name` (service.py:83, models.py:56-62; `VesselIdentity.name`).
- `agent_count` — `len(self.get_crew_manifest(...))`.
- `departments` — distinct `department` values from manifest entries.
- `watches` — populated watches from `watch_manager.get_roster()`: `[w for w, aids in roster.items() if aids]`. Empty when `watch_manager is None`. (Chosen over "current watch only" per review Recommended #4 — fuller manifest matches federation gossip use case.)
- `alert_state` — `self.get_alert_condition()` (service.py:99-100, reads `self._loader.alert_condition`, default `"GREEN"` per loader.py:57). **No `alert_manager` parameter** — alert state lives inside the ontology service itself. (Review Required #1; phantom-API removed.)
- **No `vessel_class` field** — `VesselIdentity` exposes name/version/description/instance_id/started_at only; no class field exists. Dropped from return shape. (Review Required #2.)

```python
def get_ship_manifest(
    self,
    *,
    trust_network: Any | None = None,
    watch_manager: Any | None = None,
) -> dict[str, Any]:
    """Vessel-level summary for federation gossip / workforce planning.

    Returns:
        {
            "ship_name": str,             # from VesselIdentity.name
            "agent_count": int,           # len(manifest)
            "departments": list[str],     # distinct departments
            "watches": list[str],         # populated watch names; [] if watch_manager None
            "alert_state": str,           # current alert condition (default "GREEN")
            "manifest_summary": [{"agent_type", "callsign", "department", "post"}, ...],
        }

    All enrichment params optional. Alert state is sourced from the ontology service's own
    loader; no external alert_manager needed. Designed for cheap-to-compute vessel-level
    overview for gossip subsystems.
    """
```

### Section 3 — Add `/manifest` shell command

New file: `src/probos/experience/commands/commands_manifest.py`:

```python
"""Crew Manifest shell command (AD-513 Phase 2).

Provides the `/manifest` slash command for the interactive shell. Renders a Rich
table of crew entries with optional department / watch filters, plus a `--ship`
flag for the vessel-level summary surface used by federation gossip.
"""
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
            watch = token.split(":", 1)[1].lower()  # normalize to WatchType.value casing
        elif not department:
            department = token

    if show_ship:
        summary = ontology.get_ship_manifest(
            trust_network=getattr(runtime, "trust_network", None),
            watch_manager=getattr(runtime, "watch_manager", None),
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
| 9 | `test_get_ship_manifest_alert_state_reflects_ontology_current_condition` | Default GREEN from loader; flips after `set_alert_condition("YELLOW")` |
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

grep -n "def get_alert_condition\|def get_vessel_identity\|alert_condition" src/probos/ontology/service.py
   83: def get_vessel_identity(self) -> VesselIdentity:
   94: alert_condition=self._loader.alert_condition,
   99: def get_alert_condition(self) -> str:
  100:     return self._loader.alert_condition
  102: def set_alert_condition(self, condition: str) -> None:

grep -n "alert_condition" src/probos/ontology/loader.py
   57: self.alert_condition: str = "GREEN"
  140: self.alert_condition = vessel.get("default_alert_condition", "GREEN")

grep -n "class VesselIdentity" src/probos/ontology/models.py
   56: class VesselIdentity:  # fields: name, version, description, instance_id, started_at
   #   (no `vessel_class` field — confirmed by reading lines 56-62)

grep -n "_dispatch_slash\|/agents\|handler = handlers.get" src/probos/experience/shell.py
  218: async def _dispatch_slash(self, line: str) -> None:
  226: handlers: dict[str, Any] = {
  228: "/agents": lambda: commands_status.cmd_agents(rt, con, arg),
  293: handler = handlers.get(cmd)

grep -n "/manifest" src/probos/experience/shell.py
  (0 matches — no command-name collision)

grep -n "class WatchManager\|def get_roster\|def assign_to_watch\|class WatchType\|ALPHA" src/probos/watch_rotation.py
   20: class WatchType(Enum):
   22: ALPHA = "alpha"  # value is lowercase
  136: def assign_to_watch(self, agent_id: str, watch: WatchType) -> None
  150: def get_roster(self) -> dict[str, list[str]]   # {watch_name -> [agent_id, ...]}

grep -n "watch_manager" src/probos/runtime.py | head -3
  238: watch_manager: WatchManager | None
  580: self.watch_manager = WatchManager(...)
 1659: self.watch_manager = WatchManager(...)  # warm-boot restore

grep -n "callsign_registry" src/probos/cognitive/cognitive_agent.py
 4126: rt.ontology.get_crew_manifest(callsign_registry=getattr(rt, "callsign_registry", None))
  (verified existing optional-enrichment pattern)
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

- `runtime.callsign_registry` differs from Phase 1 enrichment pattern — surface; backward-compat must hold.
- AD-513 Phase 2b/c/e scope creep — if you find yourself adding viewer-context plumbing or Tool registry integration, STOP.

## Revision (2026-05-03)

Pass-1 review (Reviews/ad-513-phase2-manifest-v1-review.md) verdict ⚠️ Conditional. All findings folded:

**Required**

- **R1 — lert_manager phantom parameter on get_ship_manifest().** Removed lert_manager: Any | None = None from the method signature, the docstring, and the cmd_manifest --ship call site. Alert state now sourced via self.get_alert_condition() (verified at service.py:99-100, reads self._loader.alert_condition, default "GREEN" per loader.py:57). Test #9 renamed to 	est_get_ship_manifest_alert_state_reflects_ontology_current_condition and asserts the verified read path: default GREEN, then flips after set_alert_condition("YELLOW").
- **R2 — essel_class undefined on VesselIdentity.** Verified class VesselIdentity at models.py:56-62 has fields name/version/description/instance_id/started_at — no class field. Dropped essel_class from the return shape (review's preferred option). Section 2 now lists each return-shape key with its verified source.

**Recommended**

- **R3 — Pin sources for ship_name / vessel_class / watches.** Section 2 now names the verified source for every return-shape key (ship_name → get_vessel_identity().name; gent_count → len(manifest); departments → distinct from manifest; watches → populated from get_roster(); lert_state → get_alert_condition()).
- **R4 — watches shape decision.** Chose option (b) — populated watches from get_roster() rather than single current watch. Federation gossip use case is better served by a fuller picture.
- **R5 — Case-normalization on /manifest watch:<arg>.** Section 3 token parser now lowercases: watch = token.split(":", 1)[1].lower(). Matches WatchType.value lowercase shape (watch_rotation.py:22).

**Section 1 watch filter spec gap (Required #2 in review)**

- Section 1 rewritten with explicit pseudo-code for: (a) the reverse-map lookup pattern gent_to_watch = {aid: w for w, aids in get_roster().items() for aid in aids}, (b) the gent_id match key with empty-string skip, (c) the watch filter with lowercase normalization. Also: when watch is set but watch_manager is None, return empty list (cannot satisfy filter).

**Nits**

- **N6 — Empty Section 5 deleted.** "### Section 5 — Pydantic config (optional). No new config required." removed.
- **N7 — 
untime.callsign_registry promoted to verified.** Footer now shows the cognitive_agent.py:4126 grep hit and drops the deferred line. (callsign_registry was already verified at the cognitive_agent and routers/ontology call sites.)
- **N8 — /manifest collision check moved to verified.** Hard-stop entry "Existing /manifest command name collides" removed; footer shows the 0-match grep against shell.py.
- **Hard-stop on 
untime.watch_manager removed** — verified at runtime.py:238/580/1659.
- **Hard-stop on "WatchManager doesn't expose query-by-watch" removed** — fallback now spelled out in Section 1 body.
- **commands_manifest.py module docstring expanded** to a sentence describing the /manifest slash command, the filter args, and the --ship flag.

**Surfaces touched (review-driven)**

- Section 1 (watch filter): full rewrite with explicit pseudo-code.
- Section 2 (ship manifest): signature drops lert_manager; return shape drops essel_class; per-key sources pinned.
- Section 3 (cmd_manifest): lert_manager kwarg removed; module docstring expanded; watch token lowercased.
- Section 5 (empty config section): removed.
- Test #9: renamed + assertion intent updated.
- Hard-Stops: 3 entries removed (collision check, watch_manager, query-by-watch fallback).
- Verified Against Codebase: footer fully refreshed with grep evidence for every concrete claim.

**Phantom-API pre-check (mandatory)**

`
./scripts/phantom-api-precheck.ps1 prompts/ad-513-phase2-manifest-v1.md
`

(Run before commit; expected 0 phantoms.)
