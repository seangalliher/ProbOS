"""AD-918: agent-initiated group-chat creation.

Lets a crew agent open + name a group chat on the ChatThreadStore substrate
(the epic substrate per the Captain ruling — NOT Ward Room), add crew
collaborators, optionally link a work item via chat_threads.task_id, and
optionally post the first message. Tagged metadata.created_by_agent=<id> so
AD-919 can surface + Captain-join it. Lifts the AD-719a-2 deferral
("agent-to-agent without a Captain seed").

Mechanism: invoked via the create_group_chat intent (handle_intent is a
bare-callable bus subscriber per the yeoman.py:242 precedent). All logic
lives here so it is testable with real fixtures (BF-287) without the bus.

Safety: per-agent cooldown + sliding-window cap (BF-163 + BF-257 shape)
prevent a create-storm. Creating a chat is reversible + low-risk, so it is
NOT consensus-gated (Safety Budget axiom: risk-proportional consensus).

Boundary (v1): this creates the room + adds participants + (optionally)
posts ONE first message. It does NOT build an agent-to-agent auto-reply
loop, and the created thread has no Captain post so AD-914 fan-out does not
auto-run on it (fan-out gates on role=="captain"). The created thread is a
normal ChatThread — a later Captain post fans out normally (AD-919), and
AD-913 add/remove_participant work on it unchanged.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.crew_utils import is_crew_agent
from probos.threads import ChatThread, ChatThreadStore
from probos.types import IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)

# AD-918: synthetic subscriber id for the bare-callable handler (yeoman.py:242
# pattern — non-agent handler under a stable id, NOT a registry entry).
GROUP_CHAT_COORDINATOR_ID = "group_chat_coordinator"

CREATE_GROUP_CHAT = "create_group_chat"

# AD-918 forward marker: descriptor for future decomposer/Captain-NL exposure.
# v1 wires the handler directly (crew agents emit via the bus); attaching this
# to a registered agent for decomposer discovery is deferred (see boundary).
CREATE_GROUP_CHAT_DESCRIPTOR = IntentDescriptor(
    name=CREATE_GROUP_CHAT,
    params={
        "title": "Name for the new group chat",
        "participants": "list of crew agent_ids or callsigns to add",
        "task_id": "optional work-item id to link the chat to",
        "first_message": "optional first message body the creator posts",
    },
    description="Open + name a crew group chat and add collaborators while working a task.",
    requires_consensus=False,  # reversible, low-risk — Safety Budget axiom (see AD-918 prompt)
    tier="utility",
)


@dataclass
class GroupChatCreateResult:
    ok: bool
    thread: ChatThread | None = None
    error: str = ""
    participants_added: list[str] = field(default_factory=list)


class AgentGroupChatService:
    """Stateful service: create-logic + per-agent rate limiting for
    agent-initiated group chats. Constructor-injected; bus-agnostic."""

    def __init__(
        self,
        *,
        store: ChatThreadStore,
        registry: Any,
        callsign_registry: Any,
        config: Any,  # GroupChatConfig
        ontology_provider: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._registry = registry
        self._callsign_registry = callsign_registry
        self._config = config
        self._ontology_provider = ontology_provider
        self._clock = clock
        # agent_id -> [monotonic create timestamps] (BF-257 sliding-window shape)
        self._create_times: dict[str, list[float]] = {}

    # ---- helpers -----------------------------------------------------

    def _ontology(self) -> Any:
        if self._ontology_provider is None:
            return None
        try:
            return self._ontology_provider()
        except Exception:
            logger.debug("AD-918: ontology provider failed", exc_info=True)
            return None

    def _is_crew(self, agent_id: str) -> bool:
        agent = self._registry.get(agent_id) if agent_id else None
        if agent is None:
            return False
        return is_crew_agent(agent, self._ontology())

    def _resolve_participant(self, ref: str) -> str | None:
        """Resolve a participant ref (agent_id OR callsign) to a crew agent_id.
        Tier-2: unresolvable / non-crew refs are dropped, not raised.

        AD-1076: resolution is LIVENESS-INDEPENDENT. Group-chat membership is
        persistent — a correctly-named crew peer that is merely idle/asleep at
        this instant still belongs in the room and sees it when it next runs.
        ``CallsignRegistry.resolve`` only returns an ``agent_id`` for a LIVE
        agent (``state in {ACTIVE, DEGRADED}``), but a proactive crew is idle
        most of the time — so a named-but-resting peer (e.g. the observed
        ``refs=['Lyra']`` suppression) used to drop, and when it was the only
        named peer the whole room was AD-966-suppressed. When the live path
        misses, fall back to any registered crew agent of the resolved type."""
        if not ref or not ref.strip():
            return None
        ref = ref.strip()
        # agent_id path
        if self._is_crew(ref):
            return ref
        # callsign path
        try:
            resolved = self._callsign_registry.resolve(ref)
        except Exception:
            logger.debug("AD-918: callsign resolve failed for %s", ref, exc_info=True)
            resolved = None
        if not resolved:
            return None
        # Live agent of the resolved type (the original AD-918 path).
        aid = resolved.get("agent_id")
        if aid and self._is_crew(aid):
            return aid
        # AD-1076: liveness-independent fallback. The callsign mapped to a type
        # but no agent of that type is currently ACTIVE/DEGRADED; resolve to a
        # registered (idle/resting) crew agent of that type so a resting peer
        # still joins the persistent room.
        agent_type = resolved.get("agent_type")
        if agent_type:
            try:
                pool = self._registry.get_by_pool(agent_type) or []
            except Exception:
                logger.debug(
                    "AD-1076: get_by_pool failed for %s", agent_type, exc_info=True,
                )
                pool = []
            for a in pool:
                cand = getattr(a, "id", None)
                if cand and self._is_crew(cand):
                    return cand
        return None

    def _rate_ok(self, creator_id: str) -> bool:
        """Cooldown + sliding-window cap. Records the timestamp on success."""
        now = self._clock()
        window = float(getattr(self._config, "agent_create_window_seconds", 3600.0))
        cooldown = float(getattr(self._config, "agent_create_cooldown_seconds", 60.0))
        cap = int(getattr(self._config, "agent_create_max_per_window", 5))
        times = self._create_times.setdefault(creator_id, [])
        times[:] = [t for t in times if now - t < window]  # prune
        if len(times) >= cap:
            return False
        if times and now - times[-1] < cooldown:
            return False
        times.append(now)
        return True

    # ---- core --------------------------------------------------------

    def create_group_chat(
        self,
        *,
        creator_id: str,
        title: str,
        participants: list[str] | None = None,
        task_id: str | None = None,
        first_message: str | None = None,
    ) -> GroupChatCreateResult:
        title = (title or "").strip()
        if not title:
            return GroupChatCreateResult(ok=False, error="empty_title")
        if not self._is_crew(creator_id):
            return GroupChatCreateResult(ok=False, error="not_crew")
        if not self._rate_ok(creator_id):
            return GroupChatCreateResult(ok=False, error="rate_limited")

        # Resolve + dedupe participants; creator is always included.
        final: list[str] = [creator_id]
        for ref in participants or []:
            aid = self._resolve_participant(ref)
            if aid and aid not in final:
                final.append(aid)

        # AD-966: ≥2-participant floor. A "group chat" with only the creator is
        # incoherent — it happens when every named ref fails to resolve to a
        # crew peer (a peer addressed only in prose, or a hallucinated/unknown
        # callsign). Minting such a room produced the Captain-reported bug where
        # an agent "started a chat with another crew member but didn't invite
        # them" (a 1-avatar room talking to an absent peer). Suppress instead of
        # creating the absent-peer monologue. This is the right chokepoint — it
        # guards all three callers (proactive AD-924, crew_executor AD-925 task
        # rooms, and the bus handle_intent), and the AD-925 task-room path always
        # passes ≥2 crew so it is unaffected. The proactive path already records a
        # ``group_chat_suppressed`` action for this result.
        if len(final) < 2:
            logger.info(
                "AD-966: group chat by %s suppressed — no named participant "
                "resolved to a crew peer (title=%r, refs=%r); not minting a "
                "1-participant room",
                creator_id, title, list(participants or []),
            )
            return GroupChatCreateResult(ok=False, error="no_participant_resolved")

        thread = self._store.create_thread(
            title=title,
            participants=final,
            task_id=task_id,
            metadata={"created_by_agent": creator_id},
        )
        if first_message and first_message.strip():
            self._store.append_message(
                thread.id,
                author_id=creator_id,
                role="agent",
                body=first_message.strip(),
                metadata={"created_by_agent": creator_id},
            )
        logger.info(
            "AD-918: %s opened group chat %s (%d participants, task_id=%s)",
            creator_id, thread.id, len(final), task_id,
        )
        return GroupChatCreateResult(ok=True, thread=thread, participants_added=final)

    # ---- bus handler -------------------------------------------------

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Bare-callable bus handler for the create_group_chat intent.

        Self-deselects (returns None) for non-matching intents so it is inert
        as a fallback subscriber. Caller identity travels in params (AD-914
        convention) — params["created_by_agent"] or params["from"]."""
        if intent.intent != CREATE_GROUP_CHAT:
            return None
        params = intent.params or {}
        creator_id = params.get("created_by_agent") or params.get("from") or ""
        result = self.create_group_chat(
            creator_id=creator_id,
            title=params.get("title", ""),
            participants=params.get("participants") or [],
            task_id=params.get("task_id"),
            first_message=params.get("first_message"),
        )
        return IntentResult(
            intent_id=intent.id,
            agent_id=GROUP_CHAT_COORDINATOR_ID,
            success=result.ok,
            result=(
                {"thread_id": result.thread.id, "participants": result.participants_added}
                if result.thread else None
            ),
            error=None if result.ok else result.error,
            confidence=1.0 if result.ok else 0.0,
        )
