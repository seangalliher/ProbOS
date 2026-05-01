# AD-468: Runtime Configuration Service — Ship's Computer

**Status:** Ready for builder
**Dependencies:** None hard. Standing Orders + Ward Room slash commands already exist (verified at `src/probos/experience/shell.py:217 _dispatch_slash`). Ship's Computer voice is already in standing orders prompts (AD-317).
**Estimated tests:** ~12
**Risk:** Medium — touches `config.py` (Pydantic models), introduces a new runtime override layer, adds a slash command. No source-of-truth mutation; `RuntimeOverrides` is a separate persistent layer that supplements `SystemConfig`.

---

## Problem

The Captain configures ProbOS today by editing `config/system.yaml` and restarting (`config.py:1597 def load_config(...)`). There is no runtime-configurable subset — settings like proactive cycle interval, dream cycle interval, and per-agent cooldowns require either a restart or are buried behind specific slash commands. There is no NL-driven path for "Computer, set Scout to run every 6 hours."

`grep -rn "runtime_overrides|class RuntimeConfig|config_service" src/probos/` returned no matches — the `runtime_overrides.toml` referenced in `prompts/wave-5-8-ad-selection-plan.md` does not exist.

## Solution Overview

Add `RuntimeConfigService` that:

1. Defines a **whitelist of overridable fields** (`OVERRIDABLE_FIELDS`) — explicitly enumerated, not blanket SystemConfig pass-through. Whitelist scope: per-agent cooldowns, proactive cycle interval, dream cycle interval, telemetry intervals.
2. Persists overrides to `runtime_overrides.toml` in the data dir.
3. Exposes `get(field)`, `set(field, value)`, `clear(field)`, and `all()` API.
4. Loads overrides at startup and applies them via the existing public APIs (e.g., `proactive_loop.set_cycle_interval(...)` if it exists; otherwise the override is simply readable by the consuming subsystem).
5. Adds a `/config` slash command that lists current overrides and accepts `set`/`clear` subcommands. NL routing through Ship's Computer is left for an HXI follow-up — this AD ships the deterministic surface.
6. Emits `EventType.CONFIG_CHANGED` on every set/clear.

This is **explicit-whitelist** by design. New override fields require an architecture decision; the runtime cannot mutate arbitrary `SystemConfig` properties.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
CONFIG_CHANGED = "config_changed"  # AD-468
```

Single new value. Verified absent via `grep -n "CONFIG_CHANGED" src/probos/events.py` (no matches).

---

## Section 1a: Add public `data_dir` property to `ProbOSRuntime`

**File:** `src/probos/runtime.py`

`runtime._data_dir` is private (verified at `runtime.py:244,289`). AD-468 needs cross-module read access for the override store path. Add a public passthrough following the AD-680 promotion pattern:

SEARCH:
```python
    # Private attributes
    _data_dir: Path
    _checkpoint_dir: Path
```

REPLACE:
```python
    # Private attributes
    _data_dir: Path
    _checkpoint_dir: Path
```

Then add the property near other public accessors (search for `@property` in `runtime.py` to find a good neighborhood):

```python
    @property
    def data_dir(self) -> Path:
        """AD-468: public read-only accessor for the runtime data directory."""
        return self._data_dir
```

This is a one-line public property — the underlying `_data_dir` stays private.

## Section 1b: Add `set_cycle_interval` and `set_cooldown` public setters to `ProactiveCognitiveLoop`

**File:** `src/probos/proactive.py`

`ProactiveCognitiveLoop._interval` and `_cooldown` are private (verified at `proactive.py:170,171`). AD-468's override application requires public setters; direct private-attr assignment from `finalize.py` is a Demeter violation.

SEARCH:
```python
    @property
    def _default_cooldown(self) -> float:
        return self._cooldown
```

REPLACE:
```python
    @property
    def _default_cooldown(self) -> float:
        return self._cooldown

    def set_cycle_interval(self, seconds: float) -> None:
        """AD-468: public setter for the proactive cycle interval (clamped 10–3600s)."""
        self._interval = max(10.0, min(3600.0, float(seconds)))

    def set_cooldown(self, seconds: float) -> None:
        """AD-468: public setter for the global proactive cooldown default (clamped 60–86400s)."""
        self._cooldown = max(60.0, min(86400.0, float(seconds)))
```

Note: `set_agent_cooldown(agent_id, cooldown)` already exists at `proactive.py:410` — that's per-agent. The new `set_cooldown` is for the global default. Both coexist.

## Section 1: `RuntimeConfigService` and override schema

**File:** `src/probos/runtime/config_service.py` (new — `runtime/` may need creation as a package; verify before writing)

> Verify-first: `src/probos/runtime/` does NOT exist as a directory (`runtime.py` is a single file). Place the new module at `src/probos/runtime_config_service.py` instead, mirroring the flat layout of `src/probos/identity.py`, `src/probos/proactive.py`, etc.

```python
"""AD-468: Runtime Configuration Service.

Whitelisted overrides persisted to runtime_overrides.json. Captain may
adjust a small set of operational parameters without editing system.yaml
and restarting.

Persistence format: JSON (stdlib only — no external dependencies).
TOML was considered but rejected because (a) writing requires the
external tomli-w package which is not currently a ProbOS dependency,
and (b) this file is written by the runtime, not edited by hand —
human-readable formatting is not the priority. JSON satisfies the
write/read round-trip with zero new dependencies.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverrideSpec:
    """Schema for one overridable field."""

    field_id: str
    typ: str   # "float" | "int" | "bool" | "str"
    description: str
    min_value: float | None = None
    max_value: float | None = None


OVERRIDABLE_FIELDS: dict[str, OverrideSpec] = {
    "proactive.interval": OverrideSpec(
        field_id="proactive.interval", typ="float",
        description="Seconds between proactive cycles",
        min_value=10.0, max_value=3600.0,
    ),
    "proactive.cooldown": OverrideSpec(
        field_id="proactive.cooldown", typ="float",
        description="Default proactive cooldown per agent (seconds)",
        min_value=60.0, max_value=86400.0,
    ),
    "dreaming.interval": OverrideSpec(
        field_id="dreaming.interval", typ="float",
        description="Seconds between dream consolidation cycles",
        min_value=300.0, max_value=86400.0,
    ),
    "telemetry.report_interval": OverrideSpec(
        field_id="telemetry.report_interval", typ="float",
        description="Seconds between telemetry reports",
        min_value=10.0, max_value=3600.0,
    ),
}


class RuntimeConfigService:
    """Persistent override layer over SystemConfig.

    Read-through: clients ask for a field, get the override if set, else None.
    Subsystems can subscribe via add_listener() to react to changes.
    Persistence is JSON via stdlib (no external dependencies).
    """

    def __init__(
        self,
        *,
        store_path: Path,
        emit_event: Any | None = None,
    ) -> None:
        self._path = store_path
        self._emit_event = emit_event
        self._overrides: dict[str, Any] = {}
        self._listeners: list[Callable[[str, Any | None], None]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._overrides = dict(data.get("overrides", {}))
            logger.info("AD-468: loaded %d runtime overrides from %s",
                        len(self._overrides), self._path)
        except Exception:
            logger.warning("AD-468: failed to load %s; starting empty",
                           self._path, exc_info=True)
            self._overrides = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump({"overrides": self._overrides}, f, indent=2, sort_keys=True)

    def get(self, field_id: str) -> Any | None:
        return self._overrides.get(field_id)

    def all(self) -> dict[str, Any]:
        return dict(self._overrides)

    def known_fields(self) -> list[OverrideSpec]:
        return list(OVERRIDABLE_FIELDS.values())

    def set(self, field_id: str, value: Any) -> tuple[bool, str]:
        spec = OVERRIDABLE_FIELDS.get(field_id)
        if spec is None:
            return False, f"unknown field: {field_id}"
        coerced, reason = self._coerce(spec, value)
        if coerced is None:
            return False, reason
        self._overrides[field_id] = coerced
        self._save()
        self._notify(field_id, coerced)
        return True, "ok"

    def clear(self, field_id: str) -> bool:
        if field_id not in self._overrides:
            return False
        del self._overrides[field_id]
        self._save()
        self._notify(field_id, None)
        return True

    def add_listener(self, fn: Callable[[str, Any | None], None]) -> None:
        self._listeners.append(fn)

    def _notify(self, field_id: str, value: Any | None) -> None:
        for fn in list(self._listeners):
            try:
                fn(field_id, value)
            except Exception:
                logger.warning("AD-468: listener failed for %s", field_id, exc_info=True)
        if self._emit_event:
            try:
                self._emit_event(
                    EventType.CONFIG_CHANGED,
                    {"field_id": field_id, "value": value, "at": time.time()},
                )
            except Exception:
                logger.warning("AD-468: CONFIG_CHANGED emit failed", exc_info=True)

    def _coerce(self, spec: OverrideSpec, raw: Any) -> tuple[Any, str]:
        try:
            if spec.typ == "float":
                v = float(raw)
            elif spec.typ == "int":
                v = int(raw)
            elif spec.typ == "bool":
                if isinstance(raw, str):
                    v = raw.lower() in ("true", "1", "yes", "on")
                else:
                    v = bool(raw)
            elif spec.typ == "str":
                v = str(raw)
            else:
                return None, f"validate spec.typ against {{float,int,bool,str}}: got {spec.typ}"
        except (TypeError, ValueError) as exc:
            return None, f"coercion failed: {exc}"
        if spec.min_value is not None and v < spec.min_value:
            return None, f"below min {spec.min_value}"
        if spec.max_value is not None and v > spec.max_value:
            return None, f"above max {spec.max_value}"
        return v, "ok"
```

---

## Section 2: Add `CONFIG_CHANGED` event type

**File:** `src/probos/events.py`

SEARCH:
```python
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
```

REPLACE:
```python
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
    CONFIG_CHANGED = "config_changed"  # AD-468
```

---

## Section 3: Add `RuntimeOverridesConfig`

**File:** `src/probos/config.py`

```python
class RuntimeOverridesConfig(BaseModel):
    """Runtime override layer configuration (AD-468)."""

    enabled: bool = True
    store_filename: str = "runtime_overrides.json"
```

Wire into `SystemConfig`:

SEARCH:
```python
    onboarding: OnboardingConfig = OnboardingConfig()
```

REPLACE:
```python
    onboarding: OnboardingConfig = OnboardingConfig()
    runtime_overrides: RuntimeOverridesConfig = RuntimeOverridesConfig()  # AD-468
```

---

## Section 4: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place after the AD-679 disclosure router block (`finalize.py:330`):

```python
    # AD-468: Runtime Configuration Service
    if config.runtime_overrides.enabled:
        from probos.runtime_config_service import RuntimeConfigService
        store_path = runtime.data_dir / config.runtime_overrides.store_filename
        rcs = RuntimeConfigService(
            store_path=store_path,
            emit_event=runtime.emit_event,
        )
        runtime.runtime_config_service = rcs
        # Apply current overrides to live subsystems via public setters
        if runtime.proactive_loop is not None:
            if (val := rcs.get("proactive.interval")) is not None:
                try:
                    runtime.proactive_loop.set_cycle_interval(float(val))
                except Exception:
                    logger.warning("AD-468: failed to apply proactive.interval override", exc_info=True)
            if (val := rcs.get("proactive.cooldown")) is not None:
                try:
                    runtime.proactive_loop.set_cooldown(float(val))
                except Exception:
                    logger.warning("AD-468: failed to apply proactive.cooldown override", exc_info=True)
        logger.info("AD-468: RuntimeConfigService wired (%d overrides loaded)",
                    len(rcs.all()))
```

> Verify-first: `runtime.data_dir` is the public property added in Section 1a. `runtime.proactive_loop` is the public attribute at `runtime.py:533, 229`. `set_cycle_interval` and `set_cooldown` are the public setters added in Section 1b. `runtime.runtime_config_service` is published as a public name (no leading underscore).

---

## Section 5: `/config` slash command

**File:** `src/probos/experience/commands/commands_config.py` (new — follows `commands_status.py` pattern verified via `grep -n "async def cmd_status" src/probos/experience/commands/commands_status.py`).

Subcommands:
- `/config` — show all current overrides + the spec list.
- `/config set <field_id> <value>` — set override.
- `/config clear <field_id>` — clear override.

```python
"""AD-468: /config slash command — runtime override management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_config(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    rcs = getattr(runtime, "runtime_config_service", None)
    if rcs is None:
        console.print("[yellow]Runtime config service disabled.[/yellow]")
        return

    parts = args.split(maxsplit=2)
    if not parts:
        _show(rcs, console)
        return

    sub = parts[0].lower()
    if sub == "set" and len(parts) == 3:
        ok, reason = rcs.set(parts[1], parts[2])
        if ok:
            console.print(f"[green]Set[/green] {parts[1]} = {parts[2]}")
        else:
            console.print(f"[red]Rejected:[/red] {reason}")
    elif sub == "clear" and len(parts) == 2:
        if rcs.clear(parts[1]):
            console.print(f"[green]Cleared[/green] {parts[1]}")
        else:
            console.print(f"[yellow]Not set:[/yellow] {parts[1]}")
    else:
        console.print("[red]Usage:[/red] /config [set <field> <value>|clear <field>]")
        _show(rcs, console)


def _show(rcs: Any, console: Console) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Field")
    table.add_column("Type")
    table.add_column("Range")
    table.add_column("Override")
    table.add_column("Description")
    overrides = rcs.all()
    for spec in rcs.known_fields():
        rng = "—"
        if spec.min_value is not None or spec.max_value is not None:
            lo = spec.min_value if spec.min_value is not None else "*"
            hi = spec.max_value if spec.max_value is not None else "*"
            rng = f"{lo}–{hi}"
        cur = overrides.get(spec.field_id, "—")
        table.add_row(spec.field_id, spec.typ, rng, str(cur), spec.description)
    console.print(table)
```

Wire into `src/probos/experience/shell.py` `handlers` dict (verified at `shell.py:225–289`):

SEARCH:
```python
            "/explain":    lambda: self._handle_nl("what just happened?"),
```

REPLACE:
```python
            "/config":     lambda: commands_config.cmd_config(rt, con, arg),
            "/explain":    lambda: self._handle_nl("what just happened?"),
```

Add `commands_config` to the import block at the top of `shell.py`:

SEARCH:
```python
    commands_introspection,
    commands_alert,
    commands_clearance,
```

REPLACE:
```python
    commands_introspection,
    commands_alert,
    commands_clearance,
    commands_config,
```

---

## Tests

**File:** `tests/test_ad468_runtime_configuration.py`

12 tests:

1. `test_event_type_config_changed_exists` — `EventType.CONFIG_CHANGED.value == "config_changed"`.
2. `test_overridable_fields_known` — `proactive.interval`, `proactive.cooldown`, `dreaming.interval`, `telemetry.report_interval` are all in `OVERRIDABLE_FIELDS`.
3. `test_set_override_persists_to_disk` — `tmp_path` store, `set("proactive.interval", 60.0)` → file exists, contents reload.
4. `test_set_override_validates_min` — `set("proactive.interval", 5.0)` (below min 10) → returns `(False, ...)`.
5. `test_set_override_validates_max` — `set("proactive.interval", 99999.0)` → rejected.
6. `test_set_override_unknown_field_rejected` — `set("foo", 1)` → `(False, "unknown field: foo")`.
7. `test_clear_removes_override` — set then clear → `get` returns None, file no longer contains the key.
8. `test_get_unset_returns_none` — fresh service, no file → `get("anything")` returns None.
9. `test_listener_fires_on_set` — `add_listener(fn)` then `set` → `fn` called once.
10. `test_emit_event_on_set` — `emit_event` called once with `EventType.CONFIG_CHANGED`.
11. `test_load_existing_file` — pre-populate `runtime_overrides.toml`, instantiate service → overrides loaded.
12. `test_coerce_string_to_float` — `set("proactive.interval", "60.0")` → succeeds with float value.

Tests use `tmp_path` fixtures and create their own service instances. No shared state. Each test cleans up via `tmp_path` lifecycle.

---

## What This Does NOT Change

- `SystemConfig` is not mutated. Overrides live in a separate persistent layer.
- `config/system.yaml` is not modified by the runtime.
- No NL routing in this AD — `/config` is the deterministic surface. Ship's Computer NL parsing is a follow-up.
- No HXI panel.
- No CLI flags. Captain uses the `/config` slash command from inside the shell.
- Whitelist is intentionally narrow. Adding new fields is an architectural decision, not a runtime user action.
- **No new package dependencies.** Persistence uses stdlib `json` (read + write). TOML was rejected because writing TOML requires the external `tomli-w` package which is not currently a ProbOS dependency. The override file is written by the runtime (not edited by hand), so JSON's lack of comments is acceptable. If a future AD wants TOML-with-comments fidelity, `tomli-w` can be added then; this AD ships dependency-free.

---

## Tracking

- `PROGRESS.md`: add `AD-468 CLOSED. Runtime Configuration Service — Ship's Computer. ...`
- `docs/development/roadmap.md`: flip AD-468 status from `*(planned)*` to `*(complete)*` near line 4183.
- `DECISIONS.md`: add an entry recording (1) the explicit-whitelist policy, (2) TOML-vs-YAML choice, (3) deferral of NL routing to a future AD.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/runtime_config_service.py`: ~210 lines (new — stdlib JSON only).
- `src/probos/runtime.py`: ~5 lines added (`@property data_dir`).
- `src/probos/proactive.py`: ~10 lines added (`set_cycle_interval`, `set_cooldown` public setters).
- `src/probos/events.py`: 1 line added.
- `src/probos/config.py`: ~8 lines added.
- `src/probos/startup/finalize.py`: ~26 lines added.
- `src/probos/experience/commands/commands_config.py`: ~70 lines (new).
- `src/probos/experience/shell.py`: ~3 lines changed (import + handler entry).
- `tests/test_ad468_runtime_configuration.py`: ~250 lines (new).
- `PROGRESS.md`, `roadmap.md`, `DECISIONS.md`: ~5 lines changed.

No `pyproject.toml` change — JSON persistence uses stdlib only.

---

## Acceptance Criteria

- All 12 tests pass under `pytest tests/test_ad468_runtime_configuration.py -v -n 0`.
- Full parallel gate `pytest tests/ -q -n 8 --dist=loadfile` is non-decreasing vs baseline.
- `EventType.CONFIG_CHANGED` is in `events.py` exactly once at the documented insertion point.
- `/config` slash command works in the REPL: shows table on bare invocation, accepts `set`/`clear`.
- Override file is written to `runtime.data_dir / "runtime_overrides.toml"`.
- Overrides are applied at startup if present.
- DECISIONS.md entry records the three architectural decisions enumerated above.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-04-30, updated 2026-05-01)

```
ls src/probos/runtime/
  (does NOT exist — runtime.py is a flat file, place new module flat)

grep -rn "runtime_overrides\|class RuntimeConfig\|config_service" src/probos/
  (no matches — AD-468 introduces these)

grep -rn "Ship's Computer" src/probos/cognitive/
  (matches in standing orders / orientation prompts only — no service)

grep -n "def load_config" src/probos/config.py
  1597: def load_config(path: str | Path) -> SystemConfig:

grep -n "DISCLOSURE_FILTERED" src/probos/events.py
  179:    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679

grep -n "onboarding: OnboardingConfig" src/probos/config.py
  1526:    onboarding: OnboardingConfig = OnboardingConfig()

grep -n "_disclosure_router = disclosure_router" src/probos/startup/finalize.py
  330:    runtime._disclosure_router = disclosure_router

grep -n "async def _dispatch_slash" src/probos/experience/shell.py
  217:    async def _dispatch_slash(self, line: str) -> None:

grep -n "commands_introspection," src/probos/experience/shell.py
  22:    commands_introspection,

grep -n "/explain" src/probos/experience/shell.py
  286:            "/explain":    lambda: self._handle_nl("what just happened?"),

grep -n "_data_dir" src/probos/runtime.py
  244:    _data_dir: Path
  289:        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
  (no public data_dir — Section 1a adds it)

grep -n "self._interval\|self._cooldown" src/probos/proactive.py
  170:        self._interval = interval
  171:        self._cooldown = cooldown
  383:        return self._cooldown
  396:        return self._agent_cooldowns.get(agent_id, self._cooldown)
  (no public setters — Section 1b adds them)

grep -n "self.proactive_loop" src/probos/runtime.py
  229:    proactive_loop: ProactiveCognitiveLoop | None
  533:        self.proactive_loop: ProactiveCognitiveLoop | None = None

grep -rn "tomli\|tomli_w\|tomli-w" pyproject.toml
  (no matches — AD-468 ships dependency-free using stdlib json)
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-468-runtime-configuration-service-review.md`:

- **Required #1 (`runtime.data_dir` phantom):** Added Section 1a — `@property def data_dir(self) -> Path` on `ProbOSRuntime`. Section 4 wiring now uses the public property.
- **Required #2 (`set_cycle_interval` phantom):** Added Section 1b — public `set_cycle_interval(seconds: float)` on `ProactiveCognitiveLoop`. Clamps to 10–3600s.
- **Required #3 (`_cooldown` direct assignment):** Section 1b also adds `set_cooldown(seconds: float)` on `ProactiveCognitiveLoop`. Section 4 wiring now uses the public setter.
- **Required #4 (`tomli-w` dependency):** Replaced TOML with stdlib JSON. `RuntimeConfigService._load`/`_save` use `json.load`/`json.dump`. No external dependency. `RuntimeOverridesConfig.store_filename` defaults to `runtime_overrides.json`. Document in "What This Does NOT Change" that TOML-with-comments fidelity is deferred.
- **Required #5 (Section 5 anchors):** confirmed correct in original draft; no change.
- **Recommended R1 (OVERRIDABLE_FIELDS public surface):** kept as module-level. Tests can import directly.
- **Recommended R2 (proactive_loop None guard):** Section 4 wiring now guards `if runtime.proactive_loop is not None:` before applying overrides.
- **Recommended R3 (verify-first path layout):** footer now includes `ls src/probos/runtime/` confirming flat layout.
- **Recommended R4 (test 11 helper):** simplified by JSON switch — JSON write is stdlib, no test fixture dance.
- **Nits:** error message for unknown typ is sharper ("validate spec.typ against {float,int,bool,str}: got X").
- **Demeter uplift (cross-cutting Wave 5):** `runtime._runtime_config_service` → `runtime.runtime_config_service` (public name). Section 4 wiring + Section 5 slash command both updated.
