"""Phase 1: Infrastructure boot (AD-517).

Starts core infrastructure services and creates the identity registry.
AD-1240: the workspace tool-result store is started after the mesh services and
before the identity registry, and is stopped by this phase's unwind if a later
step fails.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from probos.execution.workspace import WorkspaceManager
from probos.execution.workspace_result_store import WorkspaceResultStore
from probos.execution.workspace_results import (
    UnavailableWorkspaceResults,
    WorkspaceResultError,
    WorkspaceResults,
)
from probos.startup.results import InfrastructureResult

if TYPE_CHECKING:
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.gossip import GossipProtocol
    from probos.mesh.routing import HebbianRouter
    from probos.mesh.signal import SignalManager
    from probos.substrate.event_log import EventLog

logger = logging.getLogger(__name__)


def _configured_workspace_root(config: "SystemConfig") -> str | Path | None:
    """AD-1240: the configured workspace root, or None when it is missing or not a path.

    An empty value counts as missing: ``WorkspaceManager`` would resolve it to the platform
    data directory itself, which is ambient storage and never a workspace root.
    """
    configured = getattr(getattr(config, "execution", None), "workspace_root", None)
    if not isinstance(configured, (str, Path)) or not Path(configured).parts:
        return None
    return configured


async def boot_infrastructure(
    event_log: "EventLog",
    hebbian_router: "HebbianRouter",
    signal_manager: "SignalManager",
    gossip: "GossipProtocol",
    trust_network: "TrustNetwork",
    data_dir: Path,
    config: "SystemConfig",
    event_log_prune_loop_fn: Callable[[], asyncio.Future[None]],
    *,
    runtime_session_id: str = "",
    background_register: Callable[[asyncio.Task], None] | None = None,
) -> InfrastructureResult:
    """Start core infrastructure services and create the identity registry.

    Parameters
    ----------
    event_log_prune_loop_fn:
        Coroutine function to schedule as a background prune task
        (``runtime._event_log_prune_loop``).
    background_register:
        AD-824: optional callable that registers a task on the runtime's
        ``_background_tasks`` registry so the shutdown sweep can cancel
        it before the AD-820 clean-shutdown marker is written.
        AD-1240: it also receives the workspace result store's reaper task,
        which the sweep leaves alone: the store drains its own worker.
        Without it the store cannot start and stays typed-unavailable.
    """
    logger.info("Startup [infrastructure]: starting")

    # Start infrastructure
    data_dir.mkdir(parents=True, exist_ok=True)
    await event_log.start()
    execution_authority = None
    effect_broker = None
    workspace_store: WorkspaceResultStore | None = None
    try:
        protected_config = config.protected_execution
        if protected_config.enabled and protected_config.profile == "strict":
            from probos.execution.authority import ProtectedExecutionAuthority

            execution_authority = ProtectedExecutionAuthority(
                db_path=data_dir / protected_config.witness_filename,
                runtime_session_id=runtime_session_id,
                witness_busy_timeout_ms=protected_config.witness_busy_timeout_ms,
                protected_installation_root=Path(
                    protected_config.protected_installation_root
                ),
                policy_path=Path(protected_config.policy_path),
                worker_write_roots=tuple(
                    Path(root) for root in protected_config.worker_write_roots
                ),
            )
            await execution_authority.start()
            if protected_config.effect_broker_enabled:
                from probos.execution.effect_broker import GovernedEffectBroker

                effect_broker = GovernedEffectBroker(
                    authority=execution_authority,
                    runtime_session_id=runtime_session_id,
                    lease_seconds=protected_config.effect_lease_seconds,
                    max_attempts=protected_config.effect_max_attempts,
                )
                await effect_broker.start()
        event_prune_task = asyncio.create_task(
            event_log_prune_loop_fn(), name="event-log-prune-loop"
        )
        if background_register is not None:
            background_register(event_prune_task)
        await hebbian_router.start()
        await signal_manager.start()
        await gossip.start()
        await trust_network.start()

        # AD-1240: the workspace tool-result store (publication, verified readback and the
        # hourly-generation reaper) starts before the identity registry, so a failure while
        # it starts leaves nothing else open; the unwind below stops it. A store that cannot
        # start is stopped and the typed unavailable owner stays: every use of it raises
        # ``workspace_unavailable``, and nothing is redirected to ambient storage.
        workspace_results: WorkspaceResults = UnavailableWorkspaceResults()
        workspace_root = _configured_workspace_root(config)
        if workspace_root is None:
            logger.error(
                "Workspace result root configuration is missing or not a path; workspace "
                "tool-result offload stays unavailable until the next restart rather than "
                "selecting ambient storage"
            )
        else:
            workspace_store = WorkspaceResultStore(
                WorkspaceManager(workspace_root), background_register=background_register,
            )
            try:
                await workspace_store.start()
            except Exception as exc:
                logger.error(
                    "Workspace result store failed to start (%s); the store is stopped and "
                    "workspace tool-result offload stays unavailable until the next restart",
                    exc.code if isinstance(exc, WorkspaceResultError) else type(exc).__name__,
                )
                await workspace_store.stop()
                workspace_store = None
            else:
                workspace_results = workspace_store

        # --- Sovereign Agent Identity (AD-441) ---
        from probos.identity import AgentIdentityRegistry

        # AD-1196: the ship DID's key binding, built only when armed (off is byte-identical).
        identity_key_binding = None
        if config.federation.identity_keys_enabled:
            from probos.identity_key_binding import build_identity_key_binding

            identity_key_binding = build_identity_key_binding(config.federation, data_dir)

        # AD-1198 slice 2b-ii: stored incoming transfer certificates judged again by every chain stored, only while peer
        # admission is armed (off is byte-identical: no table, no re-check).
        transfer_marks = None
        if config.federation.peer_admission_enabled is True:
            from probos.identity_transfer_marks import TransferMarks

            transfer_marks = TransferMarks()

        identity_registry = AgentIdentityRegistry(
            data_dir=data_dir, key_binding=identity_key_binding, transfer_marks=transfer_marks,
        )
        await identity_registry.start()
        logger.info("identity registry started")

        logger.info("Startup [infrastructure]: complete")
        return InfrastructureResult(
            identity_registry=identity_registry,
            event_prune_task=event_prune_task,
            identity_key_binding=identity_key_binding,
            execution_authority=execution_authority,
            effect_broker=effect_broker,
            workspace_results=workspace_results,
        )
    except BaseException:
        # AD-1240: the store started after the effect broker and the authority, so it is
        # stopped first. Its stop drains the reaper and any worker thread before a
        # cancellation propagates.
        if workspace_store is not None:
            try:
                await workspace_store.stop()
            except BaseException:
                logger.error(
                    "workspace result store cleanup failed operation=boot_infrastructure "
                    "reason_code=phase_one_unwind_failed; startup remains failed"
                )
        if effect_broker is not None:
            try:
                await effect_broker.stop()
            except BaseException:
                logger.error(
                    "effect broker cleanup failed operation=boot_infrastructure "
                    "reason_code=phase_one_unwind_failed; startup remains failed"
                )
        if execution_authority is not None:
            try:
                await execution_authority.stop()
            except BaseException:
                logger.error(
                    "protected authority cleanup failed operation=boot_infrastructure "
                    "attempt_id=none manifest_id=none generation=none "
                    "reason_code=phase_one_unwind_failed; startup remains failed"
                )
        raise
