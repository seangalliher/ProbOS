"""AD-839: Work item dispatch awareness tests.

When the AD-581a WorkItemRouter direct-assigns a dispatchable work item to a
CognitiveAgent ("dispatch to agent now"), the agent must:
  * route ``work_item_dispatched`` to ``_handle_work_item_dispatch`` BEFORE the
    self-deselect fast path (the intent is not in ``_handled_intents``),
  * surface the task as a Captain message + agent acknowledgment in the DM
    thread,
  * transition the work item to ``in_progress``.

All side effects are tier-2 log-and-degrade — a failure must never raise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.types import AgentMeta, AgentState, IntentMessage, IntentResult


# ------------------------------------------------------------------ helpers

class _FakeThread:
    def __init__(self, thread_id: str = "thread-1", title: str = "test") -> None:
        self.id = thread_id
        self.title = title


class _FakeThreadStore:
    """Records appended messages; no real persistence."""

    def __init__(self) -> None:
        self.thread = _FakeThread()
        self.appended: list[dict[str, Any]] = []
        self.fail_append = False

    def get_or_create_default_for_agent(self, agent_id: str, title: str) -> _FakeThread:
        return self.thread

    def append_message(
        self,
        thread_id: str,
        author_id: str,
        role: str,
        body: str,
        metadata: dict | None = None,
    ) -> None:
        if self.fail_append:
            raise RuntimeError("thread store down")
        self.appended.append(
            {
                "thread_id": thread_id,
                "author_id": author_id,
                "role": role,
                "body": body,
                "metadata": metadata or {},
            }
        )


class _FakeWorkItem:
    def __init__(self, work_item_id: str, assigned_to: str | None = None) -> None:
        self.id = work_item_id
        self.assigned_to = assigned_to


class _FakeWorkItemStore:
    def __init__(self, assigned_to: str | None = None) -> None:
        self.transitions: list[tuple[str, str, str]] = []
        self.raise_on_transition = False
        # BF-607: track assignment so the claim path can be exercised.
        self.updates: list[tuple[str, str | None]] = []
        self._item = _FakeWorkItem("wi-1", assigned_to=assigned_to)

    async def get_work_item(self, work_item_id: str) -> Any:
        return self._item

    async def update_work_item(self, work_item_id: str, **updates: Any) -> Any:
        if "assigned_to" in updates:
            self._item.assigned_to = updates["assigned_to"]
            self.updates.append((work_item_id, updates["assigned_to"]))
        return self._item

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system"
    ) -> Any:
        if self.raise_on_transition:
            raise RuntimeError("invalid transition")
        self.transitions.append((work_item_id, new_status, source))
        return MagicMock()


def _make_runtime(thread_store: Any = None, work_item_store: Any = None) -> Any:
    rt = MagicMock()
    rt.chat_thread_store = thread_store
    rt.work_item_store = work_item_store
    rt.config.agentic_dispatch.enabled = False  # AD-856: gate off -> single-shot fallback
    return rt


def _make_agent(runtime: Any = None) -> Any:
    """Build a minimal CognitiveAgent without running __init__."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = "counselor-001"
    agent.callsign = "Ezri"
    agent.confidence = 0.5
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = 0.5
    agent._llm_client = AsyncMock()
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    return agent


def _dispatch_intent(target: str = "counselor-001", work_item_id: str = "wi-1") -> IntentMessage:
    return IntentMessage(
        intent="work_item_dispatched",
        params={
            "work_item_id": work_item_id,
            "title": "Summarize crew morale",
            "description": "Review recent logs and produce a short morale summary.",
        },
        target_agent_id=target,
    )


# ------------------------------------------------------------------ tests

@pytest.mark.asyncio
async def test_handle_intent_routes_dispatch_to_handler() -> None:
    """work_item_dispatched targeted at self routes to the handler, not self-deselect."""
    agent = _make_agent(runtime=_make_runtime())
    agent._handle_work_item_dispatch = AsyncMock(
        return_value=IntentResult(
            intent_id="i", agent_id=agent.id, success=True, result="ok", confidence=0.5
        )
    )

    intent = _dispatch_intent()
    result = await agent.handle_intent(intent)

    agent._handle_work_item_dispatch.assert_awaited_once_with(intent)
    assert result is not None
    assert result.success is True


@pytest.mark.asyncio
async def test_handle_intent_dispatch_other_agent_not_handled() -> None:
    """A dispatch targeted at a different agent is NOT claimed (self-deselect)."""
    agent = _make_agent(runtime=_make_runtime())
    agent._handle_work_item_dispatch = AsyncMock()

    intent = _dispatch_intent(target="some-other-agent")
    result = await agent.handle_intent(intent)

    agent._handle_work_item_dispatch.assert_not_awaited()
    assert result is None


@pytest.mark.asyncio
async def test_handler_transitions_and_threads_messages() -> None:
    """Happy path: transitions to in_progress and logs both thread messages."""
    thread_store = _FakeThreadStore()
    work_item_store = _FakeWorkItemStore()
    agent = _make_agent(runtime=_make_runtime(thread_store, work_item_store))
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="dm", agent_id=agent.id, success=True,
            result="On it, Captain.", confidence=0.5,
        )
    )

    result = await agent._handle_work_item_dispatch(_dispatch_intent())

    assert result.success is True
    assert result.result == "On it, Captain."
    # transitioned to in_progress with the agent as source
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]
    # captain task message + agent acknowledgment both logged
    roles = [m["role"] for m in thread_store.appended]
    assert roles == ["captain", "agent"]
    assert thread_store.appended[0]["author_id"] == "captain"
    assert thread_store.appended[1]["author_id"] == agent.id
    assert thread_store.appended[1]["body"] == "On it, Captain."


@pytest.mark.asyncio
async def test_handler_degrades_when_transition_fails() -> None:
    """A failing transition must not raise; the agent still acknowledges."""
    thread_store = _FakeThreadStore()
    work_item_store = _FakeWorkItemStore()
    work_item_store.raise_on_transition = True
    agent = _make_agent(runtime=_make_runtime(thread_store, work_item_store))
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="dm", agent_id=agent.id, success=True,
            result="Acknowledged.", confidence=0.5,
        )
    )

    result = await agent._handle_work_item_dispatch(_dispatch_intent())

    assert result.success is True
    assert result.result == "Acknowledged."
    # acknowledgment still threaded despite the transition failure
    assert thread_store.appended[-1]["role"] == "agent"


@pytest.mark.asyncio
async def test_handler_no_thread_store_still_transitions() -> None:
    """With no chat_thread_store, the handler still transitions the work item."""
    work_item_store = _FakeWorkItemStore()
    agent = _make_agent(runtime=_make_runtime(None, work_item_store))
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="dm", agent_id=agent.id, success=True,
            result="Reply.", confidence=0.5,
        )
    )

    result = await agent._handle_work_item_dispatch(_dispatch_intent())

    assert result.success is True
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]


# ------------------------------------------------------------------ BF-607

@pytest.mark.asyncio
async def test_handler_claims_unassigned_work_item() -> None:
    """BF-607: an unassigned dispatched item is claimed for the handling agent.

    The AD-581a router emits the dispatch event but never persists the
    assignment, so the board showed the item ``in_progress`` with "Unassigned".
    The handler must write ``assigned_to = self.id`` for an unassigned item.
    """
    work_item_store = _FakeWorkItemStore(assigned_to=None)
    agent = _make_agent(runtime=_make_runtime(None, work_item_store))
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="dm", agent_id=agent.id, success=True,
            result="On it.", confidence=0.5,
        )
    )

    result = await agent._handle_work_item_dispatch(_dispatch_intent())

    assert result.success is True
    # claimed for the handling agent
    assert work_item_store.updates == [("wi-1", agent.id)]
    assert work_item_store._item.assigned_to == agent.id
    # still transitioned to in_progress
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]


@pytest.mark.asyncio
async def test_handler_does_not_reassign_already_assigned_item() -> None:
    """BF-607: an item already assigned (Captain/crew) is left untouched."""
    work_item_store = _FakeWorkItemStore(assigned_to="captain-picked-agent")
    agent = _make_agent(runtime=_make_runtime(None, work_item_store))
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="dm", agent_id=agent.id, success=True,
            result="Reply.", confidence=0.5,
        )
    )

    result = await agent._handle_work_item_dispatch(_dispatch_intent())

    assert result.success is True
    # no reassignment — the existing assignee is preserved
    assert work_item_store.updates == []
    assert work_item_store._item.assigned_to == "captain-picked-agent"
    # transition still happens
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]


@pytest.mark.asyncio
async def test_handler_degrades_when_claim_fails() -> None:
    """BF-607: a failing claim must not raise; transition + ack still happen."""
    work_item_store = _FakeWorkItemStore(assigned_to=None)

    async def _boom(work_item_id: str, **updates: Any) -> Any:
        raise RuntimeError("update down")

    work_item_store.update_work_item = _boom  # type: ignore[assignment]
    agent = _make_agent(runtime=_make_runtime(None, work_item_store))
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="dm", agent_id=agent.id, success=True,
            result="Reply.", confidence=0.5,
        )
    )

    result = await agent._handle_work_item_dispatch(_dispatch_intent())

    assert result.success is True
    # claim failed but the work item still moves to in_progress
    assert work_item_store.transitions == [("wi-1", "in_progress", agent.id)]
