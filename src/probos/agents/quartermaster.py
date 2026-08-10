"""Quartermaster — Utility-tier deterministic work-board reconciler (AD-875).

Reviews the work board and acts on :class:`WorkItemReconciler` decisions
(re-dispatching live work and clearing / re-routing stale bindings) through
the existing :class:`WorkItemRouter`.  Deterministic and honest-degrade; no
LLM.  Mirrors :class:`IntrospectionAgent` in shape.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class QuartermasterAgent(BaseAgent):
    """Utility agent that re-dispatches / re-binds stranded work items."""

    agent_type = "quartermaster"
    tier = "utility"
    # AD-884: the Quartermaster's authority is scoped to reconcile-only board
    # housekeeping (unassign / re-dispatch / quarantine-flag), all reversible.
    # Per the Reversibility Preference + Minimal Authority axioms no consensus
    # gate is required; this allow-list is the regression lock for that scope.
    RECONCILE_ONLY_INTENTS: frozenset[str] = frozenset({"reconcile_board"})
    default_capabilities = [
        CapabilityDescriptor(
            can="reconcile_board",
            detail="Review the work board; re-dispatch / re-bind stranded work items",
        ),
    ]
    initial_confidence = 0.9
    intent_descriptors = [
        IntentDescriptor(
            name="reconcile_board",
            params={},
            description="Review the work board and re-dispatch or re-bind stranded work items",
            requires_reflect=False,
        ),
    ]
    _handled_intents = {"reconcile_board"}

    def __init__(
        self,
        *,
        reconciler: Any = None,
        work_item_store: Any = None,
        work_item_router: Any = None,
        emit_fn: Any = None,
        episodic: Any = None,
        scan_limit: int = 200,
        max_reconcile_attempts: int = 3,
        reconcile_backoff_seconds: int = 600,
        min_item_age_seconds: int = 30,
        stall_timeout_seconds: int = 0,
        local_node_id: str = "node-1",
        federation_enabled: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._reconciler = reconciler
        self._store = work_item_store
        self._router = work_item_router
        self._emit = emit_fn
        self._episodic = episodic
        self._scan_limit = scan_limit
        # AD-877: thrash guard — bounded re-route attempts + backoff between sweeps
        self._max_reconcile_attempts = max_reconcile_attempts
        self._reconcile_backoff_seconds = reconcile_backoff_seconds
        # AD-878: boot-race grace period — skip items younger than this age
        self._min_item_age_seconds = min_item_age_seconds
        # AD-881: live-but-stalled reroute threshold (0 = disabled, default off)
        self._stall_timeout_seconds = stall_timeout_seconds
        # AD-882: federation node-scope guard (no-op on a single node).
        self._local_node_id = local_node_id
        self._federation_enabled = federation_enabled
        # AD-883: last-sweep summary for observability (None = never run)
        self._last_sweep: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def info(self) -> dict[str, Any]:
        """AD-883: surface the last reconcile sweep via the introspection path."""
        snapshot = super().info()
        if self._last_sweep is None:
            snapshot["reconciliation"] = {"last_sweep": None}
        else:
            counts = self._last_sweep.get("counts") or {}
            snapshot["reconciliation"] = {
                "last_sweep": dict(counts),
                "age_seconds": round(time.time() - self._last_sweep["at"], 1),
                "trigger": self._last_sweep.get("trigger"),
            }
        return snapshot

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        if intent.get("intent", "") != "reconcile_board":
            return None
        return {"intent": "reconcile_board"}

    async def decide(self, observation: Any) -> Any:
        return {"action": "reconcile"}

    async def act(self, plan: Any) -> Any:
        counts = await self.reconcile()
        return {"success": True, "data": counts}

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------
    # Core sweep
    # ------------------------------------------------------------------

    async def reconcile(self) -> dict[str, Any]:
        """Review the board and act on reconciler decisions (honest-degrade)."""
        if self._store is None or self._router is None or self._reconciler is None:
            logger.info("AD-875: Quartermaster missing collaborators; reconcile skipped")
            return {"scanned": 0, "redispatched": 0, "cleared": 0, "skipped": 0, "degraded": True}

        open_items = await self._store.list_work_items(status="open", limit=self._scan_limit)
        inprog = await self._store.list_work_items(status="in_progress", limit=self._scan_limit)
        merged: dict[str, Any] = {}
        for item in (*open_items, *inprog):
            merged[item.id] = item

        counts = self._new_counts()

        # AD-879: process oldest-first within each priority band. list_work_items
        # returns created_at DESC (newest-first), so an explicit re-sort is required
        # to avoid starving the oldest stranded items under the scan_limit cap.
        if len(merged) >= self._scan_limit:
            counts["truncated"] = True
            logger.warning(
                "Board reconcile truncated: merged=%d >= scan_limit=%d; "
                "oldest items prioritized but backlog growing",
                len(merged),
                self._scan_limit,
            )
        ordered = sorted(merged.values(), key=lambda i: (i.priority, i.created_at))

        for item in ordered:
            await self._process_item(item, counts)

        if self._emit is not None:
            try:
                self._emit(EventType.WORK_ITEM_RECONCILED, dict(counts))
            except Exception:
                logger.warning("AD-875: reconcile summary emit failed", exc_info=True)

        if self._episodic is not None:
            try:
                import time as _time

                from probos.cognitive.episodic import resolve_sovereign_id
                from probos.types import Episode

                await self._episodic.store(
                    Episode(
                        user_input="[reconcile_board] quartermaster sweep",
                        timestamp=_time.time(),
                        agent_ids=[resolve_sovereign_id(self)],
                        outcomes=[dict(counts)],
                        reflection=(
                            f"Reconciled board: scanned={counts['scanned']} "
                            f"redispatched={counts['redispatched']} "
                            f"cleared={counts['cleared']} skipped={counts['skipped']}"
                        ),
                    )
                )
            except Exception:
                logger.debug("AD-875: reconcile episode store skipped", exc_info=True)

        logger.info(
            "AD-875: reconcile pass scanned=%d redispatched=%d cleared=%d skipped=%d",
            counts["scanned"],
            counts["redispatched"],
            counts["cleared"],
            counts["skipped"],
        )
        # AD-883: record last-sweep summary for the info() observability surface.
        self._last_sweep = {
            "counts": dict(counts),
            "at": time.time(),
            "trigger": "periodic",
        }
        return counts

    def _new_counts(self) -> dict[str, Any]:
        """Fresh per-sweep counts dict (shared by reconcile + reconcile_for_agent)."""
        return {
            "scanned": 0,
            "redispatched": 0,
            "cleared": 0,
            "skipped": 0,
            "degraded": False,
            # AD-877: thrash-guard counters
            "quarantined": 0,
            "quarantined_skipped": 0,
            "backoff_skipped": 0,
            # BF-730: stalled items the router may never dispatch, ended rather
            # than rerouted. Counted separately from "cleared" because nothing
            # was rerouted.
            "stranded": 0,
            # AD-879: starvation visibility
            "truncated": False,
            # AD-878: boot-race grace period skips
            "too_fresh": 0,
            # AD-881: live-but-stalled reroutes
            "stalled": 0,
            # AD-882: items skipped because owned by a remote federation node
            "remote_owner_skipped": 0,
        }

    async def _process_item(self, item: Any, counts: dict[str, Any]) -> None:
        """AD-880: per-item reconcile body (DRY — reconcile + reconcile_for_agent).

        Absorbs the AD-878 boot-race grace skip and the AD-877 quarantine/backoff/
        attempt guards. Per-item failures are Tier-2 log-and-degrade (sweep continues).
        """
        try:
            counts["scanned"] += 1
            wi = item.to_dict()
            md_current = wi.get("metadata") or {}

            # AD-878: boot-race grace period — skip items younger than the
            # grace period before any classify/attempt logic, so a mid-first-
            # dispatch item is not reclaimed and does not accrue an attempt.
            if self._min_item_age_seconds > 0:
                if wi["created_at"] > time.time() - self._min_item_age_seconds:
                    counts["too_fresh"] += 1
                    return

            # AD-877: quarantined items are terminal — never re-routed (highest precedence).
            if md_current.get("quarantined"):
                counts["quarantined_skipped"] += 1
                return

            # AD-877: backoff — skip items reconciled within the backoff window.
            if self._reconcile_backoff_seconds > 0:
                last = md_current.get("last_reconcile_at", 0) or 0
                if time.time() - float(last) < self._reconcile_backoff_seconds:
                    counts["backoff_skipped"] += 1
                    return

            is_disp = self._router.is_dispatchable(wi)
            # AD-881: the sweep owns the clock + threshold; the reconciler stays
            # pure and receives the precomputed staleness signal. updated_at is
            # last board-mutation (not a heartbeat) — a coarse stall signal.
            is_stalled = False
            if self._stall_timeout_seconds > 0 and wi.get("status") == "in_progress":
                updated_at = wi.get("updated_at") or 0
                if float(updated_at) < time.time() - self._stall_timeout_seconds:
                    is_stalled = True
            decision = self._reconciler.classify(
                wi, is_dispatchable=is_disp, is_stalled=is_stalled
            )

            if decision.action == "live_redispatch":
                await self._router.dispatch_work_item(wi)
                counts["redispatched"] += 1
            elif decision.action == "strand_terminal":
                # BF-730: a stalled item the router may never dispatch. Ends it
                # rather than rerouting it -- rerouting would replay an AD-1165
                # promoted turn's side effects, which is a worse defect than the
                # stranding it would fix.
                #
                # ``failed``, not ``cancelled``: the issue flagged the auto-close
                # policy as Captain-facing, and cancelled reads as a decision
                # someone made. This stopped without finishing and nothing
                # chose that, which is what failed means. The reason is recorded
                # on the item so the board says why.
                owner_node = md_current.get("owner_node")
                if (
                    self._federation_enabled
                    and owner_node
                    and owner_node != self._local_node_id
                ):
                    counts["remote_owner_skipped"] += 1
                    return
                fresh = await self._store.get_work_item(item.id)
                md = dict(fresh.metadata) if fresh else dict(md_current)
                md["stranded_reason"] = "stalled_not_dispatchable"
                md["stranded_at"] = time.time()
                md["last_reconcile_at"] = time.time()
                await self._store.update_work_item(
                    item.id, status="failed", metadata=md,
                )
                if self._emit is not None:
                    try:
                        self._emit(
                            EventType.WORK_ITEM_RECONCILED,
                            {
                                "work_item_id": item.id,
                                "action": "strand_terminal",
                                "reason": decision.reason,
                            },
                        )
                    except Exception:
                        logger.warning(
                            "BF-730: strand_terminal emit failed for %s",
                            item.id, exc_info=True,
                        )
                counts["stranded"] += 1
            elif decision.action == "clear_and_reroute":
                # AD-882: federation node-scope guard — an item owned by a remote
                # node only looks "not live" locally; never reclaim it (and never
                # accrue a local reconcile attempt). Default-safe no-op when
                # federation is off or no owner_node marker is present.
                owner_node = md_current.get("owner_node")
                if (
                    self._federation_enabled
                    and owner_node
                    and owner_node != self._local_node_id
                ):
                    counts["remote_owner_skipped"] += 1
                    return
                if decision.reason == "stalled":
                    counts["stalled"] += 1
                attempts = int(md_current.get("reconcile_attempts", 0))
                if attempts + 1 >= self._max_reconcile_attempts:
                    # AD-877: bounded attempts exhausted — quarantine instead of re-route.
                    fresh = await self._store.get_work_item(item.id)
                    md = dict(fresh.metadata) if fresh else dict(md_current)
                    md["quarantined"] = True
                    md["quarantine_reason"] = "max_reconcile_attempts"
                    md["quarantined_at"] = time.time()
                    md["reconcile_attempts"] = attempts + 1
                    await self._store.update_work_item(item.id, metadata=md)
                    if self._emit is not None:
                        try:
                            self._emit(
                                EventType.WORK_ITEM_QUARANTINED,
                                {
                                    "work_item_id": item.id,
                                    "reason": "max_reconcile_attempts",
                                    "attempts": attempts + 1,
                                },
                            )
                        except Exception:
                            logger.warning(
                                "AD-877: quarantine emit failed for %s", item.id, exc_info=True
                            )
                    counts["quarantined"] += 1
                    return

                # Re-route as today, and persist the attempt counter + timestamp
                # via read-modify-write (update_work_item REPLACES metadata).
                await self._store.unassign_work_item(
                    item.id, reason="quartermaster: assignee not live"
                )
                fresh = await self._store.get_work_item(item.id)
                if fresh:
                    md = dict(fresh.metadata)
                    md["reconcile_attempts"] = attempts + 1
                    md["last_reconcile_at"] = time.time()
                    await self._store.update_work_item(item.id, metadata=md)
                    refreshed = await self._store.get_work_item(item.id)
                    await self._router.dispatch_work_item((refreshed or fresh).to_dict())
                counts["cleared"] += 1
            else:
                counts["skipped"] += 1
        except Exception:
            counts["degraded"] = True
            logger.warning(
                "AD-875: reconcile failed for work item %s; continuing sweep",
                getattr(item, "id", "?"),
                exc_info=True,
            )

    async def reconcile_for_agent(self, agent_id: str) -> dict[str, Any]:
        """AD-880: reactively reclaim only the named agent's items (honest-degrade).

        Triggered by AGENT_REMOVED; complements the periodic sweep. Reuses the
        shared classify→act path (AD-877/878/879 guards) over the dead agent's
        open + in_progress items only.
        """
        if self._store is None or self._router is None or self._reconciler is None:
            logger.info(
                "AD-880: Quartermaster missing collaborators; reactive reclaim skipped for %s",
                agent_id,
            )
            return {"scanned": 0, "redispatched": 0, "cleared": 0, "skipped": 0, "degraded": True}

        open_items = await self._store.list_work_items(status="open", limit=self._scan_limit)
        inprog = await self._store.list_work_items(status="in_progress", limit=self._scan_limit)
        merged: dict[str, Any] = {}
        for item in (*open_items, *inprog):
            if item.assigned_to == agent_id:
                merged[item.id] = item

        counts = self._new_counts()
        # AD-879: oldest-first within each priority band over the filtered set.
        ordered = sorted(merged.values(), key=lambda i: (i.priority, i.created_at))
        for item in ordered:
            await self._process_item(item, counts)

        if self._emit is not None:
            try:
                self._emit(
                    EventType.WORK_ITEM_RECONCILED,
                    {**counts, "trigger": "reactive", "agent_id": agent_id},
                )
            except Exception:
                logger.warning("AD-880: reactive reconcile summary emit failed", exc_info=True)

        if self._episodic is not None:
            try:
                import time as _time

                from probos.cognitive.episodic import resolve_sovereign_id
                from probos.types import Episode

                await self._episodic.store(
                    Episode(
                        user_input=f"[reconcile_board] reactive reclaim for {agent_id}",
                        timestamp=_time.time(),
                        agent_ids=[resolve_sovereign_id(self)],
                        outcomes=[dict(counts)],
                        reflection=(
                            f"Reactive reclaim for {agent_id}: scanned={counts['scanned']} "
                            f"redispatched={counts['redispatched']} "
                            f"cleared={counts['cleared']} skipped={counts['skipped']}"
                        ),
                    )
                )
            except Exception:
                logger.debug("AD-880: reactive reclaim episode store skipped", exc_info=True)

        # AD-883: record last-sweep summary for the info() observability surface.
        self._last_sweep = {
            "counts": dict(counts),
            "at": time.time(),
            "trigger": "reactive",
        }
        return counts
