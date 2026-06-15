"""ProbOS API — Capability Packs routes (AD-1003c).

Read-only inventory of installed Capability Packs (the cross-tool agent-plugin
format, AD-1003a/b). Surfaces the AD-1003b scanner as the "installed plugins"
list, the VS Code / Copilot CLI / Claude Code equivalent. **Nothing is installed,
loaded, or executed** — the pack loader is a later slice behind the operator
trust gate.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/packs", tags=["packs"])


def _resolve_packs_dir(runtime: Any, packs_dir: str) -> Path:
    """Resolve ``packs_dir`` relative to the runtime data dir when not absolute.

    Mirrors the BF-628 lesson — resolve a configured relative path against the
    platform data dir, not the process cwd. Honest-degrade: when no data dir is
    discoverable, the path is used as-is (the scanner returns ``[]`` if it does
    not exist).
    """
    p = Path(packs_dir)
    if p.is_absolute():
        return p
    data_dir = getattr(runtime, "data_dir", None) or getattr(runtime, "_data_dir", None)
    return Path(data_dir) / p if data_dir else p


@router.get("")
async def list_packs(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-1003c: the read-only installed-pack inventory.

    Scans the configured packs directory (AD-1003b ``describe_scan``). Disabled by
    default (``packs.enabled=False``) → empty inventory + ``enabled: false``.
    Even when enabled, the scan is purely read-only — nothing is installed,
    loaded, or executed. Honest-degrade: a missing config / packs dir → empty.
    """
    cfg = getattr(getattr(runtime, "config", None), "packs", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return {
            "enabled": False,
            "packs": [],
            "counts": {"total": 0, "valid": 0, "error": 0},
        }
    from probos.packs import describe_scan

    packs_dir = _resolve_packs_dir(runtime, getattr(cfg, "packs_dir", "data/packs"))
    out = describe_scan(packs_dir)
    out["enabled"] = True
    out["packs_dir"] = str(packs_dir)
    return out
