"""ProbOS API — desktop-integration STATUS console (AD-841 v1, read-only).

A READ-ONLY status readout of the AD-751 Desktop UX Surface. It reports the
operator's *configured* desktop settings (``config.desktop``) plus a derived
"wired-this-boot" presence signal (was the lifecycle/tray/hotkey/notification
subsystem attached to the runtime this boot). It is **NOT** live OS truth, does
**NOT** enumerate apps/windows, and exposes **NO** launch/start/stop control
(that is the deferred AD-841b control half).

Two hard invariants:

* **Privacy (test-enforced):** the single-instance lock path is NEVER returned
  in full. Only ``Path(cfg.lock_file).expanduser().name`` (the basename, e.g.
  ``yeo.lock``) and a derived ``present`` boolean are exposed — never the home
  directory, the OS username, or the absolute path.
* **Presence via public attributes only (Law of Demeter):** liveness is read as
  ``getattr(runtime, "<x>", None) is not None`` against the public attrs wired
  in ``startup/finalize.py`` — never private fields (e.g. tray ``_status`` or
  hotkey ``_listening``).

Honest-degrade: any unexpected error yields the fully-defaulted OFF shape with
HTTP 200 — this endpoint never raises a 500.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _off_shape() -> dict[str, Any]:
    """Fully-defaulted OFF readout (no config / unexpected error fallback)."""
    return {
        "enabled": False,
        "active": False,
        "tray": {"active": False, "autostart": False},
        "hotkey": {"active": False, "binding": ""},
        "notifications": {"active": False, "timeout_sec": 0},
        "quiet_hours": {"start": "", "end": ""},
        "autostart_enabled": False,
        "lock": {"name": "", "present": False},
    }


@router.get("/status", dependencies=[Depends(require_crew_scope)])
async def desktop_status(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-841: read-only desktop-integration status (config-state + presence).

    Reports the operator-configured ``config.desktop`` values plus a derived
    presence signal (whether the AD-751 lifecycle/tray/hotkey/notification
    subsystems were wired this boot, read via public runtime attributes only).
    The lock file is reduced to its BASENAME — the full path is never returned.
    ``cfg is None`` (desktop unconfigured) yields a fully-defaulted OFF shape.
    Any unexpected error degrades to that same OFF shape (200, never 500).
    """
    try:
        cfg = getattr(getattr(runtime, "config", None), "desktop", None)

        # Presence — public-attribute only (Law of Demeter). These are the real
        # public attrs wired in startup/finalize.py:_wire_desktop_ux.
        active = getattr(runtime, "desktop_lifecycle", None) is not None
        tray_active = getattr(runtime, "tray_manager", None) is not None
        hotkey_active = getattr(runtime, "hotkey_listener", None) is not None
        notif_active = getattr(runtime, "notification_center", None) is not None

        # Lock — BASENAME ONLY (privacy invariant). Never leak the full path,
        # home directory, or OS username.
        name = ""
        present = False
        raw_lock = getattr(cfg, "lock_file", "") or "" if cfg is not None else ""
        if raw_lock:
            lock_path = Path(raw_lock).expanduser()
            name = lock_path.name
            try:
                present = lock_path.exists()
            except OSError:
                present = False

        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "active": active,
            "tray": {
                "active": tray_active,
                "autostart": bool(getattr(cfg, "tray_autostart", False)),
            },
            "hotkey": {
                "active": hotkey_active,
                "binding": str(getattr(cfg, "hotkey", "") or ""),
            },
            "notifications": {
                "active": notif_active,
                "timeout_sec": int(getattr(cfg, "notification_timeout_sec", 0) or 0),
            },
            "quiet_hours": {
                "start": str(getattr(cfg, "quiet_hours_start", "") or ""),
                "end": str(getattr(cfg, "quiet_hours_end", "") or ""),
            },
            "autostart_enabled": bool(getattr(cfg, "autostart_enabled", False)),
            "lock": {"name": name, "present": present},
        }
    except Exception:  # honest-degrade: never surface a 500 from a status read
        logger.warning(
            "AD-841: desktop status read failed; returning defaulted OFF shape",
            exc_info=True,
        )
        return _off_shape()
