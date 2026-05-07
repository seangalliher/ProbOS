"""AD-481f: Sealed-Core boundary helpers.

Reads config/sealed_modules.yaml, exposes is_sealed_path(path) for the Builder
pre-write check at cognitive/builder.py write sites.
"""

from __future__ import annotations

import fnmatch
import functools
import logging
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)


_DEFAULT_SEALED_CONFIG = Path("config/sealed_modules.yaml")


@functools.lru_cache(maxsize=1)
def load_sealed_globs(config_path: str | None = None) -> tuple[str, ...]:
    """Read sealed_modules.yaml and return the configured glob list.

    Cached after first read. Returns an empty tuple if the config file is
    missing or malformed (fail-open per Tier 2 log-and-degrade).
    """
    target = Path(config_path) if config_path else _DEFAULT_SEALED_CONFIG
    if not target.exists():
        logger.debug("sealed_modules.yaml not found at %s; returning empty glob list", target)
        return ()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Cannot read %s — %s; treating as empty", target, exc)
        return ()
    if not isinstance(raw, dict):
        return ()
    globs = raw.get("sealed_globs") or []
    if not isinstance(globs, list):
        return ()
    return tuple(str(g) for g in globs if isinstance(g, str))


def is_sealed_path(path: str | Path, sealed_globs: Iterable[str] | None = None) -> bool:
    """Return True if path matches any sealed glob.

    Uses fnmatch with `**` pattern interpreted as recursive (multi-segment)
    match — the canonical pattern for sealed_modules.yaml entries like
    `src/probos/substrate/**`.
    """
    if sealed_globs is None:
        sealed_globs = load_sealed_globs()
    p = str(path).replace("\\", "/")
    for glob in sealed_globs:
        glob_norm = glob.replace("\\", "/")
        # fnmatch treats `**` as `*` for path matching; emulate recursive glob
        # by also testing against a flattened form (drop the `**` segment).
        if fnmatch.fnmatch(p, glob_norm):
            return True
        if "**" in glob_norm:
            collapsed = glob_norm.replace("**", "*")
            if fnmatch.fnmatch(p, collapsed):
                return True
            # Also match parent-prefix form: glob "a/b/**" should match "a/b/c/d.py"
            prefix = glob_norm.split("**")[0].rstrip("/")
            if prefix and (p.startswith(prefix + "/") or p == prefix):
                return True
    return False
