"""AD-647d: process-chain checkpoint store for CONSULT suspend-and-resume.

Foundation cut. Provides:

    * ``ChainCheckpoint`` frozen dataclass capturing the chain name, step
      name where execution suspended, and the running context dict at the
      moment of suspension.
    * ``ChainCheckpointStore`` JSON-backed persistence (one file per
      checkpoint id) with public ``save``/``load``/``delete``/``list_ids``.
    * ``SuspendChain`` sentinel exception that handlers may raise from a
      CONSULT step to request suspension; the executor catches it,
      writes a checkpoint, and re-raises a ``ChainSuspended`` carrying
      the checkpoint id.

Foundation only — no executor-level resume yet (next AD); callers
inspect the checkpoint and resubmit via a fresh executor with the
loaded context to continue. This unblocks AD-647c CONSULT semantics
across process restarts without coupling the executor to a particular
checkpoint backend.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainCheckpoint:
    """JSON-serializable snapshot of a suspended chain at a step boundary."""

    checkpoint_id: str
    chain_name: str
    suspended_at_step: str
    suspended_at: float
    running_context: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        return d


class SuspendChain(Exception):
    """Sentinel raised by a CONSULT handler to request suspension.

    The executor catches ``SuspendChain``, writes a checkpoint via the
    configured store, and re-raises ``ChainSuspended`` carrying the
    checkpoint id back to the caller.
    """

    def __init__(self, *, reason: str = "", context_extra: dict[str, Any] | None = None) -> None:
        super().__init__(reason or "chain suspended")
        self.reason = reason
        self.context_extra = dict(context_extra or {})


class ChainSuspended(Exception):
    """Raised by the executor after a successful suspend + checkpoint write."""

    def __init__(self, *, chain_name: str, step_name: str, checkpoint_id: str) -> None:
        super().__init__(
            f"chain '{chain_name}' suspended at step '{step_name}' (checkpoint={checkpoint_id})"
        )
        self.chain_name = chain_name
        self.step_name = step_name
        self.checkpoint_id = checkpoint_id


class ChainCheckpointStore:
    """JSON-file checkpoint store. One file per checkpoint id under root."""

    def __init__(self, *, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def save(self, checkpoint: ChainCheckpoint) -> Path:
        path = self._root / f"{checkpoint.checkpoint_id}.json"
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.warning(
                "AD-647d: failed to save checkpoint %s to %s",
                checkpoint.checkpoint_id, path, exc_info=True,
            )
            raise
        return path

    def load(self, checkpoint_id: str) -> ChainCheckpoint | None:
        path = self._root / f"{checkpoint_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "AD-647d: failed to load checkpoint %s from %s",
                checkpoint_id, path, exc_info=True,
            )
            return None
        return ChainCheckpoint(
            checkpoint_id=data.get("checkpoint_id", checkpoint_id),
            chain_name=data.get("chain_name", ""),
            suspended_at_step=data.get("suspended_at_step", ""),
            suspended_at=float(data.get("suspended_at", 0.0)),
            running_context=dict(data.get("running_context", {})),
            reason=data.get("reason", ""),
        )

    def delete(self, checkpoint_id: str) -> bool:
        path = self._root / f"{checkpoint_id}.json"
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError:
            logger.warning("AD-647d: delete %s failed", path, exc_info=True)
            return False
        return True

    def list_ids(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.stem for p in self._root.glob("*.json"))


def write_checkpoint(
    store: ChainCheckpointStore,
    *,
    chain_name: str,
    step_name: str,
    running_context: dict[str, Any],
    reason: str = "",
) -> ChainCheckpoint:
    """Build and persist a ChainCheckpoint. Returns the saved record."""
    checkpoint = ChainCheckpoint(
        checkpoint_id=uuid.uuid4().hex[:16],
        chain_name=chain_name,
        suspended_at_step=step_name,
        suspended_at=time.time(),
        running_context=dict(running_context),
        reason=reason,
    )
    store.save(checkpoint)
    return checkpoint
