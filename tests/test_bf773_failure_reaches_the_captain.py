"""BF-773 (#1230): a failed tool call must reach the Captain's stored text.

The issue's scenario: Ezri's ``web_search`` was blocked, and she answered from
Microsoft Learn without saying her search had failed. BF-769 made the failure
honest at every intermediate seam -- ``IntentResult.success=False``,
``ToolCallResult.is_error=True``, the persisted trace -- and deliberately left
the final agentic text alone, which is the surface the Captain actually reads.

AD-1248 wired the disclosure through. What was missing is the test the issue
asked for, and its absence is subtle: the agentic branch was guarded ONLY by
``test_ad1248_slice_a_gaps.py:217``, which does

    source = inspect.getsource(ca.CognitiveAgent._handle_work_item_dispatch)
    assert "failures_sink=_dispatch_failures" in source

A source scan proves the call is WRITTEN, never that a failure survives to the
stored body. It cannot tell a live wire from a dead one, and it is exactly what
the issue predicted would pass while the seam stayed broken:

    "Needs a test spanning _MeshIntentTool -> ToolCallResult -> final_text,
     since every intermediate seam is already correct and would pass a
     narrower test."

These tests cross that seam behaviourally: the failure is put where the real
agentic loop puts it (``outcome.tool_failures``), and the assertion is made on
the body that reached ``ChatThreadStore``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.dm_reply import ToolFailures
from probos.substrate.agent import AgentMeta, AgentState
from probos.types import IntentMessage, IntentResult

#: The answer from the original report -- true, sourced, and concealing.
CONCEALING = "Microsoft Learn confirms the feature is available."


class _CapturingThreadStore:
    """Records what actually reached the store, which is what the Captain sees."""

    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []

    def get_or_create_default_for_agent(self, agent_id: str, title: str) -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(id="thread-1")

    def append_message(self, thread_id: str, **kwargs: Any) -> Any:
        self.appended.append({"thread_id": thread_id, **kwargs})
        return None

    def agent_body(self) -> str:
        for row in self.appended:
            if row.get("role") == "agent":
                return str(row.get("body") or "")
        return ""


class _WorkItemStore:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, str, str]] = []

    async def get_work_item(self, work_item_id: str) -> Any:
        return None

    async def transition_work_item(
        self, work_item_id: str, status: Any = None, source: str = "", **_: Any,
    ) -> bool:
        self.transitions.append((work_item_id, str(status), source))
        return True


def _runtime(thread_store: Any) -> Any:
    from types import SimpleNamespace
    return SimpleNamespace(
        chat_thread_store=thread_store,
        work_item_store=_WorkItemStore(),
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=False)),
        event_log=None,
    )


def _agent(runtime: Any) -> Any:
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestAgent)
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


def _intent() -> IntentMessage:
    return IntentMessage(
        intent="work_item_dispatched",
        params={
            "work_item_id": "wi-1",
            "title": "Research LangChain Deep Agents",
            "description": "Find out what they are.",
        },
        target_agent_id="counselor-001",
    )


def _blocked_web_search() -> ToolFailures:
    """One failed ``web_search``, never retried or superseded -- the issue's
    scenario exactly."""
    return ToolFailures.from_mapping({"web_search": "web_search"})


async def _dispatch(agent: Any, *, agentic_text: str | None,
                    failures: ToolFailures | None) -> Any:
    """Drive the real handler with the agentic branch producing ``failures``.

    Only ``_run_agentic_dispatch`` is stubbed, and it is stubbed the way the
    real one behaves: it returns the loop's final text and writes the outcome's
    failures into the sink it was handed. Everything downstream -- the
    composition, the render, the append -- is production code.
    """
    async def _fake_agentic(*, work_item_id: str, task_text: str,
                            runtime: Any, failures_sink: dict | None = None,
                            **_: Any) -> str | None:
        if failures_sink is not None:
            failures_sink["tool_failures"] = failures
        return agentic_text

    agent._run_agentic_dispatch = _fake_agentic
    return await agent._handle_work_item_dispatch(_intent())


class TestTheFailureReachesTheStoredText:

    @pytest.mark.asyncio
    async def test_a_clean_run_stores_the_answer_verbatim(self) -> None:
        """Premise. If composition altered a clean body, the difference in the
        next test could not be attributed to the disclosure."""
        store = _CapturingThreadStore()
        agent = _agent(_runtime(store))

        await _dispatch(agent, agentic_text=CONCEALING, failures=ToolFailures())

        assert store.agent_body() == CONCEALING

    @pytest.mark.asyncio
    async def test_a_concealing_answer_cannot_suppress_the_disclosure(self) -> None:
        """The issue's scenario. The model saw the failure and answered anyway
        from a different source; the Captain must still be told."""
        store = _CapturingThreadStore()
        agent = _agent(_runtime(store))

        await _dispatch(
            agent, agentic_text=CONCEALING, failures=_blocked_web_search(),
        )

        body = store.agent_body()
        assert body.startswith(CONCEALING), (
            "the model's answer must survive -- disclosure adds, never replaces"
        )
        assert "web_search" in body, (
            f"the failed tool is not named in the Captain's text: {body!r}"
        )

    @pytest.mark.asyncio
    async def test_a_run_with_no_prose_still_says_something_true(self) -> None:
        """The harder half, and the one AD-1248's comment calls out: a run that
        produced no text but DID fail a tool has the disclosure as its only
        truthful content. Gating on the raw body discards exactly that."""
        store = _CapturingThreadStore()
        agent = _agent(_runtime(store))

        await _dispatch(agent, agentic_text="", failures=_blocked_web_search())

        assert "web_search" in store.agent_body()

    @pytest.mark.asyncio
    async def test_the_returned_result_carries_it_too(self) -> None:
        """The stored row is one sink; the handler's own return value is
        another, and a caller that reads only the result must not get a
        cleaner story than the thread."""
        store = _CapturingThreadStore()
        agent = _agent(_runtime(store))

        result: IntentResult = await _dispatch(
            agent, agentic_text=CONCEALING, failures=_blocked_web_search(),
        )

        assert result is not None
        assert "web_search" in str(result.result or "")
