"""AD-721g: per-rank baseline VRM resolver.

License-clean — no avatar bytes ship in the repo. Operators install their own
``.vrm`` files (CC0 / MIT / Apache / BSD / CC-BY per AD-721i-1 whitelist) under
``<avatars_dir>/_baselines/<filename>``. The manifest tells ProbOS which
filename corresponds to which rank; the resolver maps + verifies presence.

v1 keys on Rank only. Department-aware baselines are deferred to a future AD.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import BaselineVRMManifest
    from probos.crew_profile import Rank

logger = logging.getLogger(__name__)

_BASELINES_SUBDIR = "_baselines"


def resolve_baseline_vrm_filename(
    rank: "Rank",
    manifest: "BaselineVRMManifest",
) -> str:
    """Return the manifest entry for the rank, or "" if unset.

    Pure mapping. Does NOT touch the filesystem — callers do the existence
    check via ``resolve_baseline_vrm_path``.
    """
    from probos.crew_profile import Rank

    mapping = {
        Rank.ENSIGN: manifest.ensign,
        Rank.LIEUTENANT: manifest.lieutenant,
        Rank.COMMANDER: manifest.commander,
        Rank.SENIOR: manifest.senior,
    }
    return (mapping.get(rank, "") or "").strip()


def resolve_baseline_vrm_path(
    rank: "Rank",
    manifest: "BaselineVRMManifest",
    avatars_dir: Path,
) -> Path | None:
    """Return absolute ``Path`` if the tier baseline exists on disk, else ``None``.

    Defense-in-depth: filenames must be bare names. Path separators (``/``,
    ``\\``) and parent-dir traversals (``..``) are rejected with a warning.
    """
    filename = resolve_baseline_vrm_filename(rank, manifest)
    if not filename:
        return None
    if "/" in filename or "\\" in filename or ".." in filename:
        logger.warning(
            "AD-721g: baseline VRM filename %r contains path separators or '..'; "
            "rejecting and falling back to parametric",
            filename,
        )
        return None
    base = Path(avatars_dir).resolve()
    target = (base / _BASELINES_SUBDIR / filename).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        logger.warning(
            "AD-721g: baseline %s escapes avatars_dir; rejecting",
            filename,
        )
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


__all__ = [
    "resolve_baseline_vrm_filename",
    "resolve_baseline_vrm_path",
    "_BASELINES_SUBDIR",
]
