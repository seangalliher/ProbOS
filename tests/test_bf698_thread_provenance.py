"""BF-698: chat-thread provenance survives every path into an observation.

Measured on the reference vessel 2026-07-30. The DM router resolved the thread,
wrote the Captain's message into it, and set ``IntentMessage.thread_id`` — and
the value still arrived at the conversational agentic seam as ``""``:

    22:56:12  AD-1165: agent=counselor_... has no promotable destination
              (thread=''); the turn stays inline under the chat TTL

Everything that needs the thread reads one dict key: AD-809 resolves the
per-thread personality overlay from it, AD-1066 binds produced artifacts with
it, AD-1165 promotes a long turn with it. Each degrades to a silent no-op
against an absent key, so one path that loses it takes three capabilities with
it and reports nothing.

Two fixes, tested here:

* ``perceive``'s dict-fallback branch carried neither ``thread_id`` nor
  ``intent_id``, and ~15 agents reach that branch by calling
  ``self.perceive(intent.__dict__)`` — converting the message to a dict defeats
  the ``isinstance`` check.
* the promotion/artifact thread is now resolved from the **store**, which owns
  the fact, with the dict key demoted to a preference.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    _conversational_thread_id,
)
from probos.threads import ChatThreadStore
from probos.types import IntentMessage


# ── harness ───────────────────────────────────────────────────────


class _RaisingThreadStore:
    def get_or_create_default_for_agent(self, agent_id, title):
        raise RuntimeError("db is gone")


class _CountingThreadStore:
    """Wraps a real store so we can prove it is NOT consulted unnecessarily."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0

    def get_or_create_default_for_agent(self, agent_id, title):
        self.calls += 1
        return self._inner.get_or_create_default_for_agent(agent_id, title)


def _agent(runtime=None, *, agent_id="agentezri", callsign="Ezri"):
    return SimpleNamespace(
        id=agent_id,
        callsign=callsign,
        agent_type="counselor",
        _runtime=runtime,
    )


def _resolve(agent, observation, runtime):
    return _conversational_thread_id(
        observation, runtime, agent_id=agent.id, title=agent.callsign,
    )


# ── perceive: the IntentMessage branch (regression guard) ─────────


async def test_the_intent_message_branch_still_carries_provenance() -> None:
    """The path that always worked must keep working."""
    agent = _agent()
    intent = IntentMessage(
        intent="direct_message", params={"text": "hi"}, thread_id="threadone",
    )
    obs = await CognitiveAgent.perceive(agent, intent)
    assert obs["thread_id"] == "threadone"
    assert obs["intent_id"] == intent.id


# ── perceive: the dict-fallback branch (the fix) ──────────────────


async def test_the_dict_fallback_now_carries_thread_id_and_intent_id() -> None:
    """``self.perceive(intent.__dict__)`` is how ~15 agents call this.

    Converting the message to a dict defeats the ``isinstance`` check, so this
    branch is the real production path for every one of them.
    """
    agent = _agent()
    intent = IntentMessage(
        intent="read_file", params={"path": "x"}, thread_id="threadone",
    )
    obs = await CognitiveAgent.perceive(agent, intent.__dict__)
    assert obs["thread_id"] == "threadone"
    assert obs["intent_id"] == intent.id
    # The fields that already worked are unchanged.
    assert obs["intent"] == "read_file"
    assert obs["params"] == {"path": "x"}


async def test_the_two_branches_agree_on_provenance() -> None:
    """The headline: the same message through either path yields the same keys.

    This is the assertion that would have failed before the fix, and it is the
    one that keeps the two branches from drifting apart again.
    """
    agent = _agent()
    intent = IntentMessage(
        intent="direct_message", params={"text": "hi"}, thread_id="threadone",
    )
    via_object = await CognitiveAgent.perceive(agent, intent)
    via_dict = await CognitiveAgent.perceive(agent, intent.__dict__)
    for key in ("intent", "params", "context", "intent_id", "thread_id"):
        assert via_object[key] == via_dict[key], f"{key} diverges between branches"


async def test_a_hand_built_dict_without_provenance_is_untouched() -> None:
    """Preserves the deliberate AD-432 contract (``TestPerceiveIntentId``).

    The fallback must not invent provenance it was never given. Only a source
    that actually carries ``id`` / ``thread_id`` — i.e. an ``IntentMessage``
    passed as ``__dict__`` — gets them, so fixing the fifteen real callers does
    not change what a hand-built dict produces.
    """
    agent = _agent()
    obs = await CognitiveAgent.perceive(agent, {"intent": "ping", "params": {}})
    assert "intent_id" not in obs
    assert "thread_id" not in obs
    # Absent and None are indistinguishable to every real consumer.
    assert obs.get("thread_id") is None
    assert obs["intent"] == "ping"


async def test_a_non_dict_intent_degrades_rather_than_raising() -> None:
    agent = _agent()
    obs = await CognitiveAgent.perceive(agent, "not-a-dict")
    assert obs["intent"] == "unknown"
    assert obs["params"] == {}
    assert obs.get("thread_id") is None


async def test_an_explicit_none_thread_id_is_still_carried() -> None:
    """A message with no thread is different from a dict with no thread key.

    ``IntentMessage.thread_id`` defaults to None, so ``__dict__`` carries the
    key with a None value. That must survive as a present-but-None key, the
    same shape the IntentMessage branch produces.
    """
    agent = _agent()
    intent = IntentMessage(intent="direct_message", params={})
    obs = await CognitiveAgent.perceive(agent, intent.__dict__)
    assert "thread_id" in obs
    assert obs["thread_id"] is None


# ── resolution order ──────────────────────────────────────────────


@pytest.fixture
def real_store(tmp_path: Path):
    return ChatThreadStore(tmp_path / "threads.db")


def test_the_observation_key_wins_and_the_store_is_not_consulted(real_store) -> None:
    counting = _CountingThreadStore(real_store)
    runtime = SimpleNamespace(chat_thread_store=counting)
    obs = {"thread_id": "fromobservation", "params": {"thread_id": "fromparams"}}
    assert _resolve(_agent(runtime), obs, runtime) == "fromobservation"
    assert counting.calls == 0


def test_params_are_used_when_the_observation_key_is_empty(real_store) -> None:
    """Still this turn's thread — preferred over the canonical fallback."""
    counting = _CountingThreadStore(real_store)
    runtime = SimpleNamespace(chat_thread_store=counting)
    obs = {"thread_id": "", "params": {"thread_id": "fromparams"}}
    assert _resolve(_agent(runtime), obs, runtime) == "fromparams"
    assert counting.calls == 0


def test_the_store_resolves_the_canonical_thread_as_a_last_resort(real_store, caplog) -> None:
    runtime = SimpleNamespace(chat_thread_store=real_store)
    agent = _agent(runtime)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        resolved = _resolve(agent, {"thread_id": "", "params": {}}, runtime)

    assert resolved
    thread = real_store.get_thread(resolved)
    assert thread is not None
    assert "agentezri" in thread.participants
    # The compensation is a WARNING, not silence: something upstream dropped
    # provenance it was handed, and that is the signal that finds it.
    assert any("BF-698" in r.getMessage() for r in caplog.records)


def test_the_canonical_thread_is_stable_across_turns(real_store) -> None:
    """Two promoted turns must not land in two different threads."""
    runtime = SimpleNamespace(chat_thread_store=real_store)
    agent = _agent(runtime)
    first = _resolve(agent, {"thread_id": "", "params": {}}, runtime)
    second = _resolve(agent, {"thread_id": "", "params": {}}, runtime)
    assert first == second


def test_it_matches_the_thread_the_dm_router_would_have_used(real_store) -> None:
    """Same call the router makes, so the report lands where the Captain is."""
    runtime = SimpleNamespace(chat_thread_store=real_store)
    router_thread = real_store.get_or_create_default_for_agent("agentezri", "Ezri")
    resolved = _resolve(_agent(runtime), {"thread_id": "", "params": {}}, runtime)
    assert resolved == router_thread.id


# ── degrade paths: never worse than today ─────────────────────────


def test_no_store_returns_empty_exactly_as_before() -> None:
    runtime = SimpleNamespace(chat_thread_store=None)
    assert _resolve(_agent(runtime), {"thread_id": "", "params": {}}, runtime) == ""


def test_a_raising_store_returns_empty_and_warns(caplog) -> None:
    runtime = SimpleNamespace(chat_thread_store=_RaisingThreadStore())
    agent = _agent(runtime)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        assert _resolve(agent, {"thread_id": "", "params": {}}, runtime) == ""
    assert any("BF-698" in r.getMessage() for r in caplog.records)


def test_malformed_params_do_not_raise(real_store) -> None:
    runtime = SimpleNamespace(chat_thread_store=real_store)
    agent = _agent(runtime)
    for params in ("not-a-dict", None, 7, []):
        assert _resolve(agent, {"thread_id": "", "params": params}, runtime)


def test_a_thread_object_without_an_id_degrades_to_empty() -> None:
    class _OddStore:
        def get_or_create_default_for_agent(self, agent_id, title):
            return SimpleNamespace()

    runtime = SimpleNamespace(chat_thread_store=_OddStore())
    assert _resolve(_agent(runtime), {"thread_id": "", "params": {}}, runtime) == ""


# ── the seam: the resolved id reaches the executor ────────────────


class _CaptureExecutor:
    last_kwargs: dict | None = None

    def __init__(self, *, llm_client) -> None:
        pass

    async def run(self, **kwargs):
        _CaptureExecutor.last_kwargs = kwargs
        return SimpleNamespace(final_text="done")


async def test_the_resolved_thread_reaches_the_executor(monkeypatch, real_store) -> None:
    """AD-1066 binds produced artifacts with this value.

    With the observation key empty it was receiving ``""``, so a document an
    agent produced mid-chat had no thread to land on. Resolving once fixes the
    artifact binding and the AD-1165 promotion together.
    """
    from probos.config import DmAgenticConfig

    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _CaptureExecutor,
    )
    _CaptureExecutor.last_kwargs = None
    runtime = SimpleNamespace(
        config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True)),
        chat_thread_store=real_store,
    )
    agent = _agent(runtime)
    agent._llm_client = object()
    agent._promoted_turn_tasks = set()
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )

    text = await CognitiveAgent._maybe_run_conversational_agentic(
        agent,
        {"intent": "direct_message", "params": {}},  # no thread_id anywhere
        system_prompt="You are Ezri.",
        user_message="make me a doc",
    )

    assert text == "done"
    resolved = _CaptureExecutor.last_kwargs["thread_id"]
    assert resolved, "the executor received an empty thread_id — artifacts cannot bind"
    assert resolved == real_store.get_or_create_default_for_agent("agentezri", "Ezri").id
