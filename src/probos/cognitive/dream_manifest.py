"""AD-538b: DreamManifest -- per-episode skip-already-processed marker.

stdlib JSON-backed; persists at runtime.data_dir/dream_manifest.json.
Atomic write per Wave 5 convention #2.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class DreamManifest:
    """Tracks which (episode_id, step) pairs have been processed.

    v1 schema: ``{"<episode_id>": {"<step>": <unix_ts>}}``. The unix
    timestamp is the moment of marking and is consumed by
    ``prune(max_age_seconds)``.

    Public API:
      - ``mark_processed(episode_id, step)`` -- record the pair.
      - ``is_processed(episode_id, step) -> bool`` -- query.
      - ``prune(max_age_seconds)`` -- drop entries older than the threshold.
    """

    def __init__(self, *, store_path: Path | None = None) -> None:
        self._store_path = store_path
        self._entries: dict[str, dict[str, float]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded or self._store_path is None:
            return
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for ep_id, steps in raw.items():
                        if isinstance(ep_id, str) and isinstance(steps, dict):
                            self._entries[ep_id] = {
                                str(s): float(t or 0.0)
                                for s, t in steps.items()
                                if isinstance(s, str)
                            }
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "AD-538b: dream manifest read failed (path=%s); starting empty",
                    self._store_path, exc_info=True,
                )
        self._loaded = True

    def _save(self) -> bool:
        if self._store_path is None:
            return False
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._entries), encoding="utf-8")
            os.replace(tmp, self._store_path)
            return True
        except OSError:
            logger.error(
                "AD-538b: dream manifest write failed (path=%s)",
                self._store_path, exc_info=True,
            )
            return False

    def mark_processed(self, episode_id: str, step: str) -> None:
        if not episode_id or not step:
            return
        self._load()
        bucket = self._entries.setdefault(episode_id, {})
        bucket[step] = time.time()
        self._save()

    def is_processed(self, episode_id: str, step: str) -> bool:
        if not episode_id or not step:
            return False
        self._load()
        return step in self._entries.get(episode_id, {})

    def prune(self, max_age_seconds: float) -> int:
        """Drop entries older than max_age_seconds. Returns count removed."""
        self._load()
        cutoff = time.time() - max_age_seconds
        removed = 0
        for ep_id in list(self._entries.keys()):
            steps = self._entries[ep_id]
            for step in list(steps.keys()):
                if steps[step] < cutoff:
                    del steps[step]
                    removed += 1
            if not steps:
                del self._entries[ep_id]
        if removed:
            self._save()
        return removed
