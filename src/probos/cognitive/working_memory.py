"""Working memory manager — bounded LLM context assembly."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — assembles trust summary for LLM context
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 characters
CHARS_PER_TOKEN = 4


@dataclass
class WorkingMemorySnapshot:
    """A serializable snapshot of system state for the LLM context."""

    active_intents: list[dict[str, Any]] = field(default_factory=list)
    recent_results: list[dict[str, Any]] = field(default_factory=list)
    agent_summary: dict[str, Any] = field(default_factory=dict)
    trust_summary: list[dict[str, Any]] = field(default_factory=list)
    top_connections: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    # AD-573b: extension fields (all defaulted-empty; backward compatible)
    relational_links: list[dict[str, Any]] = field(default_factory=list)
    scratchpad: list[str] = field(default_factory=list)
    commitments: list[dict[str, Any]] = field(default_factory=list)

    def to_text(self) -> str:
        """Serialize to text for LLM context."""
        sections = []

        sections.append("## System State")

        if self.agent_summary:
            sections.append(f"Crew: {self.agent_summary.get('crew', 0)} agents")
            pools = self.agent_summary.get("pools", {})
            if pools:
                pool_parts = [f"  {name}: {info}" for name, info in pools.items()]
                sections.append("Pools:\n" + "\n".join(pool_parts))

        if self.capabilities:
            sections.append(f"Available capabilities: {', '.join(self.capabilities)}")

        if self.trust_summary:
            sections.append("Trust scores:")
            for ts in self.trust_summary[:5]:
                sections.append(
                    f"  agent={ts['agent_id'][:8]} "
                    f"score={ts.get('score', 0):.2f}"
                )

        if self.top_connections:
            sections.append("Top Hebbian connections:")
            for tc in self.top_connections[:5]:
                sections.append(
                    f"  {tc['source'][:8]} -> {tc['target'][:8]} "
                    f"weight={tc.get('weight', 0):.4f}"
                )

        if self.active_intents:
            sections.append(f"Active intents: {len(self.active_intents)}")
            for ai in self.active_intents[:3]:
                sections.append(f"  {ai.get('intent', '?')}: {ai.get('status', '?')}")

        if self.recent_results:
            sections.append(f"Recent results: {len(self.recent_results)}")
            for rr in self.recent_results[:3]:
                sections.append(
                    f"  {rr.get('intent', '?')}: "
                    f"success={rr.get('success', '?')}"
                )

        return "\n".join(sections)

    def token_estimate(self) -> int:
        """Estimate token count for this snapshot."""
        return len(self.to_text()) // CHARS_PER_TOKEN


class WorkingMemoryManager:
    """Assembles and manages the bounded working memory context.

    Gathers system state from registry, trust network, Hebbian weights,
    and recent intents. Enforces a configurable token budget by evicting
    lower-priority items when the context exceeds the limit.
    """

    def __init__(
        self,
        token_budget: int = 4000,
    ) -> None:
        self.token_budget = token_budget
        self._recent_results: list[dict[str, Any]] = []
        self._active_intents: list[dict[str, Any]] = []
        self._max_recent = 20
        # AD-573b: relational links / scratchpad / commitments (bounded rings)
        self._relational_links: list[dict[str, Any]] = []
        self._scratchpad: list[str] = []
        self._commitments: list[dict[str, Any]] = []
        self._max_relational = 32
        self._max_scratchpad = 16
        self._max_commitments = 8
        # AD-573f: commitment lifecycle event emission (late-bind)
        self._emit_event_fn: Any | None = None

    # ------------------------------------------------------------------
    # AD-573f: event-callback late-bind (mirror BilletRegistry pattern)
    # ------------------------------------------------------------------

    def set_event_callback(self, emit_fn: Any) -> None:
        """Late-bind COMMITMENT_RECORDED emission target."""
        self._emit_event_fn = emit_fn

    def _emit_commitment_event(
        self, action: str, commitment_id: str,
    ) -> None:
        if self._emit_event_fn is None:
            return
        try:
            from probos.events import EventType  # local import: avoid cycle at module load
            self._emit_event_fn(
                EventType.COMMITMENT_RECORDED,
                {"commitment_id": commitment_id, "action": action},
            )
        except Exception:
            logger.warning(
                "AD-573f: COMMITMENT_RECORDED emit failed (action=%s, id=%s)",
                action, commitment_id, exc_info=True,
            )

    # ------------------------------------------------------------------
    # AD-573b: extension helpers (best-effort; never raise per Wave-5 tier-2)
    # ------------------------------------------------------------------

    def record_relation(self, from_id: str, to_id: str, kind: str = "mention") -> None:
        try:
            if not from_id or not to_id:
                return
            self._relational_links.append(
                {"from": from_id, "to": to_id, "kind": kind}
            )
            if len(self._relational_links) > self._max_relational:
                self._relational_links = self._relational_links[-self._max_relational:]
        except Exception:
            logger.warning("AD-573b: record_relation failed", exc_info=True)

    def add_scratchpad(self, text: str) -> None:
        try:
            if not text:
                return
            self._scratchpad.append(text)
            if len(self._scratchpad) > self._max_scratchpad:
                self._scratchpad = self._scratchpad[-self._max_scratchpad:]
        except Exception:
            logger.warning("AD-573b: add_scratchpad failed", exc_info=True)

    def add_commitment(
        self, commitment_id: str, summary: str, due_at: float | None = None,
    ) -> None:
        try:
            if not commitment_id:
                return
            entry: dict[str, Any] = {
                "id": commitment_id,
                "summary": summary,
            }
            if due_at is not None:
                entry["due"] = due_at
            self._commitments.append(entry)
            if len(self._commitments) > self._max_commitments:
                self._commitments = self._commitments[-self._max_commitments:]
        except Exception:
            logger.warning("AD-573b: add_commitment failed", exc_info=True)
            return
        # AD-573f: emit AFTER successful add (best-effort)
        self._emit_commitment_event("record", commitment_id)

    # ------------------------------------------------------------------
    # AD-573f: commitment lifecycle helpers
    # ------------------------------------------------------------------

    def mark_commitment_complete(self, commitment_id: str) -> None:
        """Mutate matching dict's status key in-place; emit COMMITMENT_RECORDED.

        No-op if ``commitment_id`` not found (best-effort per Wave-5 tier-2).
        """
        try:
            for entry in self._commitments:
                if entry.get("id") == commitment_id:
                    entry["status"] = "done"
                    self._emit_commitment_event("complete", commitment_id)
                    return
            # not found — silent no-op
        except Exception:
            logger.warning(
                "AD-573f: mark_commitment_complete failed for id=%s",
                commitment_id, exc_info=True,
            )

    def pending_commitments(self) -> list[dict[str, Any]]:
        """Return commitments without a terminal status (done / expired)."""
        return [
            c for c in self._commitments
            if c.get("status") not in ("done", "expired")
        ]

    def expired_commitments(self, now: float) -> list[dict[str, Any]]:
        """Return commitments whose ``due`` is past ``now`` and not yet completed."""
        return [
            c for c in self._commitments
            if c.get("due") is not None
            and c["due"] < now
            and c.get("status") != "done"
        ]

    def record_intent(self, intent: str, params: dict[str, Any]) -> None:
        """Record an intent as active."""
        self._active_intents.append({
            "intent": intent,
            "params": params,
            "status": "active",
        })
        # Keep bounded
        if len(self._active_intents) > self._max_recent:
            self._active_intents = self._active_intents[-self._max_recent:]

    def record_result(
        self,
        intent: str,
        success: bool,
        result_count: int = 0,
        detail: str = "",
    ) -> None:
        """Record an intent result."""
        self._recent_results.append({
            "intent": intent,
            "success": success,
            "result_count": result_count,
            "detail": detail,
        })
        # Remove from active
        self._active_intents = [
            a for a in self._active_intents if a["intent"] != intent
        ]
        # Keep bounded
        if len(self._recent_results) > self._max_recent:
            self._recent_results = self._recent_results[-self._max_recent:]

    def assemble(
        self,
        registry: AgentRegistry | None = None,
        trust_network: TrustNetwork | None = None,
        hebbian_router: HebbianRouter | None = None,
        capability_list: list[str] | None = None,
    ) -> WorkingMemorySnapshot:
        """Assemble a working memory snapshot from current system state.

        Gathers data from all available sources, then evicts lower-priority
        items if the token budget is exceeded.
        """
        snapshot = WorkingMemorySnapshot(
            active_intents=list(self._active_intents),
            recent_results=list(self._recent_results),
        )

        # Agent summary from registry
        if registry:
            summary_data = registry.summary()
            snapshot.agent_summary = {
                "total": registry.count,
                "crew": registry.crew_count(),
                "pools": summary_data,
            }

        # Trust summary
        if trust_network:
            snapshot.trust_summary = trust_network.summary()

        # Top Hebbian connections
        if hebbian_router:
            all_w = hebbian_router.all_weights()
            # Sort by weight descending, take top 10
            sorted_w = sorted(all_w.items(), key=lambda x: x[1], reverse=True)
            snapshot.top_connections = [
                {"source": src, "target": tgt, "weight": w}
                for (src, tgt), w in sorted_w[:10]
            ]

        # Available capabilities
        if capability_list:
            snapshot.capabilities = capability_list

        # Evict if over budget
        self._evict_to_budget(snapshot)

        return snapshot

    def _evict_to_budget(self, snapshot: WorkingMemorySnapshot) -> None:
        """Remove lower-priority items until within token budget."""
        # Priority order for eviction (lowest priority first):
        # 1. top_connections (trim)
        # 2. trust_summary (trim)
        # 3. recent_results (trim oldest)
        # 4. active_intents (trim oldest)

        while snapshot.token_estimate() > self.token_budget:
            if len(snapshot.top_connections) > 2:
                snapshot.top_connections.pop()
                continue
            if len(snapshot.trust_summary) > 2:
                snapshot.trust_summary.pop()
                continue
            if len(snapshot.recent_results) > 1:
                snapshot.recent_results.pop(0)
                continue
            if len(snapshot.active_intents) > 1:
                snapshot.active_intents.pop(0)
                continue
            break  # Can't evict further
