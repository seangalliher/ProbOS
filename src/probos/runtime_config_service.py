"""AD-468: Runtime Configuration Service.

Whitelisted overrides persisted to runtime_overrides.json. Captain may
adjust a small set of operational parameters without editing system.yaml
and restarting.

Persistence format: JSON (stdlib only - no external dependencies).
TOML was considered but rejected because (a) writing requires the
external tomli-w package which is not currently a ProbOS dependency,
and (b) this file is written by the runtime, not edited by hand -
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
    typ: str
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
            logger.info(
                "AD-468: loaded %d runtime overrides from %s",
                len(self._overrides), self._path,
            )
        except Exception:
            logger.warning(
                "AD-468: failed to load %s; starting empty",
                self._path, exc_info=True,
            )
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
                logger.warning(
                    "AD-468: listener failed for %s", field_id, exc_info=True,
                )
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
                v: Any = float(raw)
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
