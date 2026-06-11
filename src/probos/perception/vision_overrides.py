"""AD-982a: persistent Captain-set vision-capability overrides.

The vision gate (``CallsignRegistry._type_to_profile[agent_type]["vision_capable"]``)
is loaded from the crew-profile YAML at boot, and the AD-720d-2.1 approve path
only flips it in memory — so a Captain grant was lost on restart. This sidecar
records the Captain's explicit grants/revokes (keyed by ``agent_type``, matching
the gate) and re-applies them onto the registry at boot, so the grant is
PERMANENT without mutating the tracked YAML (config = declared defaults; this
data-dir store = runtime overrides on top).

Mirrors the AD-720d-2.1 ``vision_proposal_history`` sidecar: module-level state,
RLock, atomic temp-file + ``replace`` writes, Tier-2 log-and-degrade on disk
failure, ``configure(path)`` bound once at startup.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

# agent_type -> explicit Captain setting (True granted / False revoked). Absence
# means "no override" → the YAML default stands.
_overrides: dict[str, bool] = {}
_lock = RLock()
_path: Path | None = None


def configure(path: Path | None) -> None:
    """Bind the on-disk sidecar (called once at startup from runtime.py).

    ``None`` disables persistence (in-memory only). Existing contents load on
    bind; a malformed file falls back to empty and logs at WARNING (Tier-2).
    """
    global _path, _overrides
    with _lock:
        _path = path
        if path is None:
            return
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _overrides = {str(k): bool(v) for k, v in raw.items()}
            else:
                logger.warning(
                    "AD-982a: vision overrides file %s is not an object; "
                    "starting empty", path,
                )
                _overrides = {}
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "AD-982a: failed to load vision overrides from %s; starting "
                "empty. err=%s", path, exc,
            )
            _overrides = {}


def set_override(agent_type: str, enabled: bool) -> None:
    """Record the Captain's explicit grant (``True``) or revoke (``False``)
    for ``agent_type`` and persist."""
    if not agent_type:
        return
    with _lock:
        _overrides[agent_type] = bool(enabled)
        _persist_locked()


def get_override(agent_type: str) -> bool | None:
    """The Captain's explicit setting for ``agent_type``, or ``None`` when
    there is no override (the YAML default stands)."""
    with _lock:
        return _overrides.get(agent_type)


def all_overrides() -> dict[str, bool]:
    """Snapshot of every override (copy on read)."""
    with _lock:
        return dict(_overrides)


def apply(callsign_registry: Any) -> int:
    """Re-apply every override onto the live registry at boot. Returns the
    count applied. Called AFTER ``load_from_profiles`` so the override wins.

    Tier-2: a registry without ``set_vision_capable_by_type`` (or a per-type
    failure) is skipped; never raises into startup.
    """
    setter = getattr(callsign_registry, "set_vision_capable_by_type", None)
    if setter is None:
        return 0
    applied = 0
    for agent_type, enabled in all_overrides().items():
        try:
            if setter(agent_type, enabled):
                applied += 1
        except Exception:
            logger.warning(
                "AD-982a: failed to apply vision override for agent_type=%s",
                agent_type, exc_info=True,
            )
    if applied:
        logger.info("AD-982a: applied %d persisted vision override(s) at boot", applied)
    return applied


def reset_all() -> None:
    """Test helper: clear in-memory state and persist the empty map."""
    with _lock:
        _overrides.clear()
        _persist_locked()


def _persist_locked() -> None:
    """Atomic write — caller MUST hold ``_lock``."""
    if _path is None:
        return
    try:
        tmp = _path.with_suffix(_path.suffix + ".tmp")
        tmp.write_text(json.dumps(_overrides, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(_path)
    except OSError as exc:
        logger.warning(
            "AD-982a: failed to persist vision overrides to %s; in-memory "
            "state remains authoritative. err=%s", _path, exc,
        )
