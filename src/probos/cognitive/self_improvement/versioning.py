"""AD-482g v1: Agent Versioning.
AD-482h v1: Git-Backed Agent Persistence -- `LocalDiskPersistence` default impl.
AD-482i v1: Shadow Deployment Protocol seam + NoOp default.

Three converging concerns in one module:

* `AgentVersion` dataclass + `AgentVersionStore` track parent-version lineage
  and per-version trust metadata for designed agents.
* `AgentPersistence` Protocol + `LocalDiskPersistence` default impl write
  promoted agent source to ``{root}/{agent_type}_v{N}.py`` (``{data_dir}/promoted-agents``
  unless configured; never inside the source checkout, BF-937) plus a
  ``{agent_type}_v{N}.meta.yaml`` sidecar. Git PR creation is the
  AD-482h-1 follow-on (subprocess git + GitHub MCP wiring is its own AD).
* `ShadowDeploymentPolicy` Protocol + `NoOpShadowDeploymentPolicy` default
  ship as Protocol seam. Concrete impl is AD-482i-1 (parallel-pool comparator
  with scaler-aware shadow workers -- needs AD-280 territory).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, TYPE_CHECKING

from probos.cognitive.builder_paths import operator_checkout_refusal

if TYPE_CHECKING:
    from probos.cognitive.self_mod import DesignedAgentRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentVersion:
    """Version metadata for a designed agent."""

    version: int
    parent_version: int | None
    designed_at: float
    designer: str
    trust_alpha_at_promotion: float
    trust_beta_at_promotion: float
    source_hash: str
    persisted_path: str | None = None


@dataclass(frozen=True)
class ShadowComparisonResult:
    """Result of a shadow comparison between baseline and candidate versions.

    Concrete impl in AD-482i-1; v1 only ships the dataclass shape so the
    NoOp default can return a typed `None` without consumers crashing on
    field access.
    """

    baseline_version: int
    candidate_version: int
    baseline_score: float
    candidate_score: float
    sample_size: int
    confident_winner: int | None  # version number of winner, or None if tie/insufficient


class AgentPersistence(Protocol):
    """AD-482h v1: write a promoted agent's source to a permanent location."""

    async def promote(
        self,
        record: Any,  # DesignedAgentRecord
        version: AgentVersion,
    ) -> str:
        """Persist the record's source. Return the persisted path or "" on degrade."""
        ...


class ShadowDeploymentPolicy(Protocol):
    """AD-482i v1 (Protocol seam): compare baseline vs candidate versions in shadow.

    NoOp default returns None; AD-482i-1 follow-on ships a concrete impl once
    the parallel-pool comparator (AD-280 territory) lands.
    """

    async def shadow_compare(
        self,
        *,
        baseline_version: AgentVersion,
        candidate_version: AgentVersion,
        runtime: Any,
    ) -> ShadowComparisonResult | None:
        ...


class NoOpShadowDeploymentPolicy:
    """Default ShadowDeploymentPolicy. Always returns None (no-op)."""

    async def shadow_compare(
        self,
        *,
        baseline_version: AgentVersion,
        candidate_version: AgentVersion,
        runtime: Any,
    ) -> ShadowComparisonResult | None:
        return None


def compute_source_hash(source_code: str) -> str:
    """Stable SHA-256 hex digest of source code (first 16 chars)."""
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]


#: BF-937 (#1678): the checkout this module runs from (src/probos/cognitive/self_improvement -> repository), the one
#: ``builder.py`` and ``routers/build.py`` protect with ``operator_checkout_refusal`` (BF-897). An installed package has no
#: ``.git`` entry there, and the rule then finds no checkout to protect.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[4]

#: BF-937 (#1678): the directory under the data directory that promoted agent source goes to when no root is configured.
PROMOTED_AGENTS_DIRNAME = "promoted-agents"


def resolve_promoted_agents_dir(root_dir: str, data_dir: str | Path) -> Path:
    """BF-937 (#1678): where promoted agent source is written: *root_dir* when set, else ``{data_dir}/promoted-agents``.

    The one place the default is named (the shape of ``probos.config.resolve_records_repo_path``). A relative *root_dir* is
    relative to the current directory, as ``Path.mkdir`` reads it, and ``~`` is not expanded.
    """
    if root_dir:
        return Path(root_dir)
    return Path(data_dir) / PROMOTED_AGENTS_DIRNAME


def persistence_root_refusal(root_dir: str | Path) -> str | None:
    """BF-937 (#1678): why promoted agent source must not be written under *root_dir*, or None if it may be.

    A repository change goes through GitHub (AD-1336), so promoted source is never written into the checkout ProbOS runs
    from. The rule is ``operator_checkout_refusal`` (BF-897) over ``_CHECKOUT_ROOT``: *root_dir* is resolved (links and
    junctions followed, a relative path against the current directory, case and 8.3 names by file identity) and refused
    when its nearest ``.git`` entry is the checkout's; a linked worktree has its own and is allowed, and so is a directory
    outside any checkout. No git command runs. A path that cannot be examined is refused.
    """
    if operator_checkout_refusal(root_dir, _CHECKOUT_ROOT) is None:
        return None
    return (
        f"promoted agent source is not written into the source checkout: {str(root_dir)!r} is inside the checkout "
        f"ProbOS runs from ({_CHECKOUT_ROOT}), or could not be checked against it (BF-937). A repository change goes "
        "through GitHub (AD-1336). Leave self_improvement.persistence_root_dir empty to use {data_dir}/promoted-agents, "
        "or name a directory outside the checkout."
    )


class LocalDiskPersistence:
    """AD-482h v1: write promoted agent source to local disk.

    Args:
        root_dir: Directory under which agent files are written. Required: this class names no location of its own
            (BF-937: it was ``src/probos/agents/designed``, inside the checkout). A root inside the source checkout is
            refused with ``ValueError``; a relative root is resolved against the current directory when the object is built.
        clock: Time source for sidecar metadata.
    """

    def __init__(
        self,
        *,
        root_dir: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        refusal = persistence_root_refusal(root_dir)
        if refusal is not None:
            raise ValueError(refusal)
        self._root = Path(root_dir).resolve()
        self._clock = clock

    async def promote(self, record: Any, version: AgentVersion) -> str:
        """Write {agent_type}_v{N}.py + sidecar. Tier-2 log-and-degrade.

        Returns the persisted path on success, or "" on failure, or when the root is inside the source checkout (BF-937).
        """
        agent_type = getattr(record, "agent_type", "")
        source_code = getattr(record, "source_code", "")
        if not agent_type or not source_code:
            logger.warning(
                "AD-482h: promote skipped -- record missing agent_type or source_code",
            )
            return ""
        refusal = persistence_root_refusal(self._root)
        if refusal is not None:
            # BF-937 (#1678): the root was allowed when this object was built; a link swapped in since is judged now.
            logger.error("BF-937: LocalDiskPersistence.promote refused for %s: %s", agent_type, refusal)
            return ""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            file_path = self._root / f"{agent_type}_v{version.version}.py"
            meta_path = self._root / f"{agent_type}_v{version.version}.meta.yaml"
            file_path.write_text(source_code, encoding="utf-8")
            meta_lines = [
                f"agent_type: {agent_type}",
                f"version: {version.version}",
                f"parent_version: {version.parent_version if version.parent_version is not None else 'null'}",
                f"designed_at: {version.designed_at}",
                f"designer: {version.designer}",
                f"trust_alpha_at_promotion: {version.trust_alpha_at_promotion}",
                f"trust_beta_at_promotion: {version.trust_beta_at_promotion}",
                f"source_hash: {version.source_hash}",
                f"promoted_at: {self._clock()}",
            ]
            meta_path.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")
            return str(file_path)
        except Exception:
            logger.warning(
                "AD-482h: LocalDiskPersistence.promote failed for %s",
                agent_type,
                exc_info=True,
            )
            return ""


class AgentVersionStore:
    """In-memory version history per agent_type.

    Optional `RecordsStore` write-through for persistence is the AD-482g-1
    follow-on; v1 ships in-memory only.
    """

    def __init__(
        self,
        *,
        event_emit_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._versions: dict[str, list[AgentVersion]] = {}
        self._emit = event_emit_fn

    def register_version(self, agent_type: str, version: AgentVersion) -> int:
        """Append a version to the history. Returns the version number."""
        history = self._versions.setdefault(agent_type, [])
        history.append(version)
        if self._emit is not None:
            try:
                self._emit(
                    "AGENT_VERSION_PROMOTED",
                    {
                        "agent_type": agent_type,
                        "version": version.version,
                        "parent_version": version.parent_version,
                        "persisted_path": version.persisted_path or "",
                        "source_hash": version.source_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-482g: AGENT_VERSION_PROMOTED emit failed for %s v%d",
                    agent_type,
                    version.version,
                    exc_info=True,
                )
        return version.version

    def latest(self, agent_type: str) -> AgentVersion | None:
        history = self._versions.get(agent_type)
        if not history:
            return None
        return history[-1]

    def history(self, agent_type: str) -> list[AgentVersion]:
        return list(self._versions.get(agent_type, []))

    def known_types(self) -> list[str]:
        return sorted(self._versions.keys())

    def next_version_number(self, agent_type: str) -> int:
        """Return the next sequential version number for ``agent_type``."""
        history = self._versions.get(agent_type)
        if not history:
            return 1
        return max(v.version for v in history) + 1
