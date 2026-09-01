"""BF-813 (#1277): three consumers that mishandled an authorization denial.

Each finding was reproduced by execution against the real consumer, with a
CONTROL that behaves differently -- so "the defect is present" could not be
confused with "the probe never reached the code". One earlier attempt at
finding 2 used a single ``@mention``, took the single-agent path, and produced
an empty ``per_agent_replies`` on the control; that is how it was caught rather
than reported as an absence.

Measured before the fix::

    1. DENIED status=403 after={'dm': 1, ...} tier=high   (control: dm 0, low)
    2. thread_appends=[..., ('agent', 'counselor-001', '(refused -- not
       permitted)')]  episodic_written=2   (control: 2 real prose replies)
    3. DENIED returned=True introduction_sent=True emissions=1 dwell_set=True
       -- byte-identical to the delivered control

After::

    1. DENIED after={'dm': 0, ...} tier=low
    2. thread_appends drop the refusal; episodic_written=1 (the allowed one)
    3. DENIED returned=False emissions=0

The dwell clock is deliberately NOT refunded in (3): a refused attempt costs a
dwell so a standing refusal cannot re-attempt on every eligible frame, while
the delivery allowance is reserved for emissions that reach the Captain.

Review also established that (1) needed a bigger change than the denial path.
The bracket was split across modules -- ``agent_chat`` entered, step 8 of the
reply pipeline exited -- and FOUR separate ways of not reaching that step each
orphaned the refcount silently: a 403, a cancellation before dispatch, an error
shaping the response, and a ``mark_reply_emitted`` that raised inside step 8
(``_run_steps`` swallows it, so that one returned HTTP 200). The route now owns
the whole bracket in a ``finally``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.api_models import PerAgentReply
from probos.avatars import sampling_state as sampling_state_module
from probos.avatars.sampling_state import AvatarSamplingStateMachine
from probos.config import (
    AuthConfig,
    CognitiveConfig,
    SamplingRatesConfig,
    SystemConfig,
)
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied


# ---------------------------------------------------------------------------
# Shared doubles
# ---------------------------------------------------------------------------


class _DenyingBus:
    """Models the real contract: the raise happens ONLY on opt-in."""

    def __init__(self) -> None:
        self.opted_in: list[bool] = []

    async def send(self, intent: Any, *, raise_on_denial: bool = False, **_: Any) -> Any:
        self.opted_in.append(raise_on_denial)
        if raise_on_denial:
            raise IntentAuthorizationDenied(
                intent_name=str(getattr(intent, "intent", "direct_message")),
                reason="test-policy", entry_point="send",
            )
        return None


class _AllowingBus:
    _DEFAULT = object()

    def __init__(self, result: Any = _DEFAULT) -> None:
        self.opted_in: list[bool] = []
        # A sentinel, NOT ``result or default``: a test that needs a genuine
        # ``None`` envelope was silently handed a success namespace instead,
        # so it asserted nothing about the boundary it named.
        self._result = (
            SimpleNamespace(result="Aye, Captain.", error=None)
            if result is _AllowingBus._DEFAULT else result
        )

    async def send(self, intent: Any, *, raise_on_denial: bool = False, **_: Any) -> Any:
        self.opted_in.append(raise_on_denial)
        return self._result


def _base_runtime(bus: Any, data_dir: Path) -> Any:
    rt = MagicMock()
    rt.intent_bus = bus
    rt.config = SystemConfig(cognitive=CognitiveConfig(), auth=AuthConfig())
    # BOTH names: ``create_app`` prefers ``_data_dir``, and on a MagicMock that
    # attribute is a truthy mock, so it wins and the app mkdirs a ``MagicMock/``
    # directory in the repo root.
    rt.data_dir = str(data_dir)
    rt._data_dir = str(data_dir)
    # A MagicMock ontology is truthy, so the crew gate would 400 before the bus
    # is ever called and the route would prove nothing.
    rt.ontology = None
    return rt


# ===========================================================================
# Finding 1 -- /api/agent/{id}/chat leaks avatar sampling state on denial
# ===========================================================================


def _chat_runtime(bus: Any, data_dir: Path, *, held_seconds: float | None = None) -> Any:
    rt = _base_runtime(bus, data_dir)
    rt.registry.get.return_value = SimpleNamespace(
        id="counselor-001", agent_type="counselor", callsign="Ezri",
        instructions="x", state="active",
    )
    rt.avatar_sampling_state = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    rt.avatar_event_bus = None
    if held_seconds is None:
        rt.deferred_turn_queue = None
    else:
        rt.deferred_turn_queue = SimpleNamespace(held_for=lambda _tid: held_seconds)
    return rt


def test_a_denied_agent_chat_releases_the_dm_sampling_it_entered(tmp_path: Path) -> None:
    # Arrange
    bus = _DenyingBus()
    rt = _chat_runtime(bus, tmp_path)
    client = TestClient(create_app(rt), raise_server_exceptions=False)

    # Act
    response = client.post("/api/agent/counselor-001/chat", json={"message": "hi"})

    # Assert -- premise first: without the 403 and the opt-in, the request was
    # refused somewhere else and the counts below prove nothing.
    assert response.status_code == 403, response.text
    assert bus.opted_in == [True]
    assert rt.avatar_sampling_state.snapshot_counts("counselor-001")["dm"] == 0
    assert rt.avatar_sampling_state.current_tier("counselor-001") == "low"


def test_an_allowed_agent_chat_ends_at_zero_without_double_exiting(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Control, and the other half of the contract.

    A zero count alone cannot show single ownership, because the spurious-exit
    clamp also lands on zero; the absence of the clamp's warning is what
    discriminates.
    """
    # Arrange
    rt = _chat_runtime(_AllowingBus(), tmp_path)
    client = TestClient(create_app(rt), raise_server_exceptions=False)

    # Act
    with caplog.at_level(logging.WARNING, logger=sampling_state_module.logger.name):
        response = client.post("/api/agent/counselor-001/chat", json={"message": "hi"})

    # Assert
    assert response.status_code == 200, response.text
    assert rt.avatar_sampling_state.snapshot_counts("counselor-001")["dm"] == 0
    spurious = [
        r for r in caplog.records
        if r.name == sampling_state_module.logger.name and "spurious exit_dm" in r.getMessage()
    ]
    assert not spurious, f"the route double-exited: {[r.getMessage() for r in spurious]}"


def test_a_held_thread_also_ends_at_zero(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A held turn skips the dispatch entirely and must still balance."""
    # Arrange
    bus = _AllowingBus()
    rt = _chat_runtime(bus, tmp_path, held_seconds=42.0)
    client = TestClient(create_app(rt), raise_server_exceptions=False)

    # Act
    with caplog.at_level(logging.WARNING, logger=sampling_state_module.logger.name):
        response = client.post("/api/agent/counselor-001/chat", json={"message": "hi"})

    # Assert -- premise: the hold really did short-circuit the dispatch, so the
    # only send seen is the pipeline's own downstream one, never the route's
    # opted-in dispatch.
    assert response.status_code == 200, response.text
    assert True not in bus.opted_in, "the route's dispatch was not skipped"
    assert rt.avatar_sampling_state.snapshot_counts("counselor-001")["dm"] == 0
    spurious = [
        r for r in caplog.records
        if r.name == sampling_state_module.logger.name and "spurious exit_dm" in r.getMessage()
    ]
    assert not spurious, f"the route double-exited: {[r.getMessage() for r in spurious]}"


def test_the_release_survives_a_sampling_state_that_raises(tmp_path: Path) -> None:
    """The release runs while a denial is in flight; it must not replace it."""
    # Arrange
    bus = _DenyingBus()
    rt = _chat_runtime(bus, tmp_path)
    boom = MagicMock()
    boom.exit_dm.side_effect = RuntimeError("state machine unavailable")
    rt.avatar_sampling_state = boom
    client = TestClient(create_app(rt), raise_server_exceptions=False)

    # Act
    response = client.post("/api/agent/counselor-001/chat", json={"message": "hi"})

    # Assert: still the denial, not a 500.
    assert response.status_code == 403, response.text
    assert boom.exit_dm.called


@pytest.mark.asyncio
async def test_step_8_no_longer_touches_dm_sampling() -> None:
    """Ownership is not split across modules any more.

    Step 8 used to hold the matched ``exit_dm``, one module away and near the
    end of a 22-step chain. ``_run_steps`` swallows a step's exception, so a
    ``mark_reply_emitted`` that raised took the exit with it and returned HTTP
    200 with the refcount elevated. Re-adding an exit here would now
    double-decrement, so pin its absence.
    """
    from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
    from probos.dm_reply import DmReply

    # Arrange
    machine = AvatarSamplingStateMachine(rates=SamplingRatesConfig())
    machine.enter_dm("counselor-001")
    agent = MagicMock()
    ctx = DmReplyContext(
        runtime=MagicMock(), agent=agent, agent_id="counselor-001",
        callsign="ezri", req_message="hi", reply=DmReply(body="hi"),
        has_image_attachment=False, per_attachment=[], sanity_gate=None,
        params={}, message_text="hi",
        sampling_state=machine, avatar_event_bus=None,
    )

    # Act
    await DmReplyPipeline(ctx).step_8_mark_emitted()

    # Assert -- premise: the step really ran.
    assert agent.mark_reply_emitted.called
    assert machine.snapshot_counts("counselor-001")["dm"] == 1


@pytest.mark.asyncio
async def test_a_cancellation_before_dispatch_still_balances(tmp_path: Path) -> None:
    """``observe_self_avatar``'s guard is ``except Exception``, so a
    cancellation there escapes -- one of the four measured leak paths.

    Driven through the PUBLIC ``agent_chat``. Calling the impl and supplying
    the ``finally`` here would pass against a wrapper that released ordinary
    exceptions and leaked cancellation, which is the thing under test.
    """
    from probos.api_models import AgentChatRequest
    from probos.routers.agents import agent_chat

    # Arrange
    rt = _chat_runtime(_AllowingBus(), tmp_path)
    rt.registry.get.return_value = SimpleNamespace(
        id="counselor-001", agent_type="counselor", callsign="Ezri",
        instructions="x", state="active",
        observe_self_avatar=AsyncMock(side_effect=asyncio.CancelledError()),
    )

    # Act / Assert
    with pytest.raises(asyncio.CancelledError):
        await agent_chat("counselor-001", AgentChatRequest(message="hi"), rt)

    assert rt.avatar_sampling_state.snapshot_counts("counselor-001")["dm"] == 0


def test_the_guard_is_a_no_op_when_the_handler_never_entered(tmp_path: Path) -> None:
    """The route has deliberate early returns BEFORE entering (the crew gate,
    AD-732 honest-degrade). Releasing then would decrement a CONCURRENT
    request's count, which is worse than the leak."""
    from probos.routers.agents import _DmSamplingGuard

    # Arrange: another request already holds the bracket.
    rt = _chat_runtime(_AllowingBus(), tmp_path)
    rt.avatar_sampling_state.enter_dm("counselor-001")
    guard = _DmSamplingGuard(rt, "counselor-001")

    # Act
    guard.release()

    # Assert
    assert rt.avatar_sampling_state.snapshot_counts("counselor-001")["dm"] == 1


def test_the_guard_releases_exactly_once(tmp_path: Path) -> None:
    """One-shot: a second release must not steal another request's count."""
    from probos.routers.agents import _DmSamplingGuard

    # Arrange
    rt = _chat_runtime(_AllowingBus(), tmp_path)
    guard = _DmSamplingGuard(rt, "counselor-001")
    guard.enter()
    rt.avatar_sampling_state.enter_dm("counselor-001")  # a concurrent request

    # Act
    guard.release()
    guard.release()

    # Assert
    assert rt.avatar_sampling_state.snapshot_counts("counselor-001")["dm"] == 1


# ===========================================================================
# Finding 2 -- a refusal is stored and rendered as agent prose
# ===========================================================================


class _PerAgentBus:
    """Denies exactly one target, allows the others."""

    def __init__(self, deny_agent: str, *, fail_agent: str = "") -> None:
        self.deny = deny_agent
        self.fail = fail_agent
        self.reply_text = "Aye, Captain."
        self.calls: list[str] = []

    async def send(self, intent: Any, *, raise_on_denial: bool = False, **_: Any) -> Any:
        target = str(getattr(intent, "target_agent_id", ""))
        self.calls.append(target)
        if target == self.deny and raise_on_denial:
            raise IntentAuthorizationDenied(
                intent_name="direct_message", reason="test-policy", entry_point="send",
            )
        if target == self.fail:
            raise RuntimeError("transport exploded")
        return SimpleNamespace(result=self.reply_text, error=None)


class _ThreadStore:
    def __init__(self) -> None:
        self.appended: list[dict[str, Any]] = []

    def get_or_create_system_thread(self, *a: Any, **k: Any) -> Any:
        return SimpleNamespace(id="main")

    def get_or_create_default_for_agent(self, *a: Any, **k: Any) -> Any:
        return SimpleNamespace(id="main")

    def append_message(self, thread_id: str, **kw: Any) -> None:
        self.appended.append(kw)


class _Episodic:
    """Async, because production AWAITS the store call.

    A synchronous double let the append be recorded and then raised
    ``TypeError: object NoneType can't be used in 'await' expression`` inside
    the route's log-and-degrade guard -- so the tests were proving the episode
    was SUBMITTED, never that the sink accepted it.
    """

    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store_episode(self, ep: Any) -> None:
        self.stored.append(ep)

    async def store(self, ep: Any) -> None:
        self.stored.append(ep)

    async def add_episode(self, ep: Any) -> None:
        self.stored.append(ep)


_CALLSIGNS = {"ezri": "counselor-001", "data": "ops-001"}


def _fanout_runtime(bus: Any, data_dir: Path) -> Any:
    rt = _base_runtime(bus, data_dir)
    rt.chat_thread_store = _ThreadStore()
    rt.episodic_memory = _Episodic()
    rt.dream_adapter = None
    rt.callsign_registry.resolve.side_effect = lambda cs: (
        {"agent_id": _CALLSIGNS[cs.lower()], "callsign": cs}
        if cs.lower() in _CALLSIGNS else None
    )
    return rt


def _fanout(bus: Any, data_dir: Path, *, message: str = "@Ezri @Data hello") -> tuple[Any, Any]:
    rt = _fanout_runtime(bus, data_dir)
    client = TestClient(create_app(rt), raise_server_exceptions=False)
    response = client.post("/api/chat", json={"message": message})
    return rt, response


def _agent_rows(rt: Any) -> list[tuple[str, str]]:
    return [
        (str(a.get("author_id")), str(a.get("body")))
        for a in rt.chat_thread_store.appended
        if a.get("role") == "agent"
    ]


def _episode_agents(rt: Any) -> list[list[str]]:
    return [list(getattr(ep, "agent_ids", []) or []) for ep in rt.episodic_memory.stored]


def test_two_allowed_recipients_are_both_recorded(tmp_path: Path) -> None:
    """Premise for every assertion below.

    A first attempt at this used ONE mention, silently took the single-agent
    path, and produced no fan-out replies at all -- an absence that would have
    read as "the defect is fixed".
    """
    # Arrange / Act
    rt, response = _fanout(_PerAgentBus(deny_agent="__nobody__"), tmp_path)

    # Assert
    assert response.status_code == 200, response.text
    assert [t for _, t in _agent_rows(rt)] == ["Aye, Captain.", "Aye, Captain."]
    assert _episode_agents(rt) == [["counselor-001"], ["ops-001"]]


def test_a_refused_recipient_is_not_recorded_as_having_spoken(tmp_path: Path) -> None:
    # Arrange / Act
    rt, response = _fanout(_PerAgentBus(deny_agent="counselor-001"), tmp_path)

    # Assert: the allowed recipient is recorded; the refused one is not -- in
    # EITHER sink. An episode carrying the placeholder becomes recallable
    # context, so the ship would remember an agent announcing its own refusal.
    assert response.status_code == 200, response.text
    assert _agent_rows(rt) == [("ops-001", "Aye, Captain.")]
    assert _episode_agents(rt) == [["ops-001"]]


def test_a_refusal_is_still_reported_to_the_captain_and_typed(tmp_path: Path) -> None:
    """Not recorded is not the same as hidden.

    The Captain must still see that this recipient did not answer, and the
    entry carries a machine-readable status so a consumer never has to
    string-match server prose to tell an utterance from a placeholder.
    """
    # Arrange / Act
    _rt, response = _fanout(_PerAgentBus(deny_agent="counselor-001"), tmp_path)

    # Assert
    replies = {r["callsign"].lower(): r for r in response.json()["per_agent_replies"]}
    assert replies["ezri"]["status"] == "refused"
    assert "refused" in replies["ezri"]["text"].lower()
    assert replies["data"]["status"] == ""


def test_a_failed_delivery_is_also_kept_out_of_episodic_memory(tmp_path: Path) -> None:
    """Nearby, same loop: the transcript already skipped "(delivery failed)",
    the episodic sink did not -- it skipped only on a missing agent_id."""
    # Arrange / Act
    rt, response = _fanout(
        _PerAgentBus(deny_agent="__nobody__", fail_agent="counselor-001"), tmp_path,
    )

    # Assert
    assert response.status_code == 200, response.text
    replies = {r["callsign"].lower(): r for r in response.json()["per_agent_replies"]}
    assert replies["ezri"]["status"] == "delivery_failed", "the failure path was not reached"
    assert _episode_agents(rt) == [["ops-001"]]


def test_an_agent_that_genuinely_says_a_placeholder_is_still_recorded(tmp_path: Path) -> None:
    """The predicate is typed, not string-matched.

    Gating on prose dropped a real reply whose text happened to equal a
    server placeholder -- the ship silently forgetting something an agent
    actually said.
    """
    # Arrange
    bus = _PerAgentBus(deny_agent="__nobody__")
    bus.reply_text = "(delivery failed)"

    # Act
    rt, response = _fanout(bus, tmp_path)

    # Assert
    assert response.status_code == 200, response.text
    assert all(r["status"] == "" for r in response.json()["per_agent_replies"])
    assert _agent_rows(rt) == [
        ("counselor-001", "(delivery failed)"), ("ops-001", "(delivery failed)"),
    ]
    assert _episode_agents(rt) == [["counselor-001"], ["ops-001"]]


def test_the_status_field_defaults_to_empty() -> None:
    """Additive: every existing producer keeps working unchanged."""
    reply = PerAgentReply(agent_id="a", callsign="c", text="hello")
    assert reply.status == ""


# ===========================================================================
# Finding 3 -- the proactive observer spends its budget before dispatch
# ===========================================================================


def _observer(bus: Any) -> Any:
    from probos.perception.observer import ProactiveBudget, ProactiveVisionObserver

    obs = object.__new__(ProactiveVisionObserver)
    obs._runtime = SimpleNamespace(intent_bus=bus, perception_mode_controller=None)
    obs._budget = ProactiveBudget()
    obs._state = {}
    return obs


async def _emit(obs: Any, *, first: bool = True) -> bool:
    return await obs._decide_and_emit(
        session_id="s-1", agent_id="counselor-001",
        observation=SimpleNamespace(novelty_score=0.99),
        is_first_observation=first,
    )


def _state(obs: Any) -> Any:
    return obs._state[("s-1", "counselor-001")]


@pytest.mark.asyncio
async def test_a_delivered_emission_does_spend_the_budget() -> None:
    """Premise. If the budget never moved even on delivery, its absence under
    a denial would prove nothing."""
    # Arrange
    bus = _AllowingBus(result=object())
    obs = _observer(bus)

    # Act
    delivered = await _emit(obs)

    # Assert
    assert delivered is True
    assert bus.opted_in == [True]
    assert _state(obs).introduction_sent is True
    assert _state(obs).proactive_emissions == 1
    assert _state(obs).last_emission_at != 0.0


@pytest.mark.asyncio
async def test_a_refused_emission_does_not_spend_the_budget() -> None:
    # Arrange
    bus = _DenyingBus()
    obs = _observer(bus)

    # Act
    delivered = await _emit(obs)

    # Assert: premise first -- the dispatch really was attempted and refused.
    assert bus.opted_in == [True]
    assert delivered is False
    assert _state(obs).introduction_sent is False
    assert _state(obs).proactive_emissions == 0


@pytest.mark.asyncio
async def test_a_failed_dispatch_does_not_spend_the_budget() -> None:
    """A transport failure is not a delivery either."""
    # Arrange
    class _ExplodingBus:
        async def send(self, _i: Any, **_k: Any) -> Any:
            raise RuntimeError("transport exploded")

    obs = _observer(_ExplodingBus())

    # Act
    delivered = await _emit(obs)

    # Assert
    assert delivered is False
    assert _state(obs).proactive_emissions == 0


@pytest.mark.asyncio
async def test_a_refused_high_novelty_emission_leaves_the_dwell_clock_alone() -> None:
    """The mid-session trigger has the same shape as the introduction."""
    # Arrange
    bus = _DenyingBus()
    obs = _observer(bus)

    # Act
    delivered = await _emit(obs, first=False)

    # Assert
    assert bus.opted_in == [True], "the mid-session dispatch was never attempted"
    assert delivered is False
    assert _state(obs).proactive_emissions == 0


@pytest.mark.asyncio
async def test_concurrent_frames_cannot_both_pass_a_budget_of_one() -> None:
    """Refunding must not become check-then-act across a suspension point.

    A first cut simply moved the mutation after the ``await``. Measured with
    two concurrent frames against ``max_emissions=1``: both passed the gate and
    both dispatched. ``VisionConsumer`` releases its describe lock before
    invoking the observer, so this is reachable.
    """
    from probos.perception.observer import ProactiveBudget

    # Arrange: a bus that suspends, so the two calls interleave.
    class _SlowBus:
        def __init__(self) -> None:
            self.sends = 0

        async def send(self, _i: Any, **_k: Any) -> Any:
            self.sends += 1
            await asyncio.sleep(0)
            return object()

    bus = _SlowBus()
    obs = _observer(bus)
    obs._budget = ProactiveBudget(max_emissions_per_session=1, min_dwell_seconds=30.0)

    # Act
    results = await asyncio.gather(_emit(obs, first=True), _emit(obs, first=False))

    # Assert -- premise: both calls really did run.
    assert len(results) == 2
    assert _state(obs).proactive_emissions <= 1, (
        f"budget of 1 was overspent: emissions={_state(obs).proactive_emissions}"
    )
    assert bus.sends <= 1, f"dispatched {bus.sends} times against a budget of 1"


@pytest.mark.asyncio
async def test_a_refusal_costs_a_dwell_so_it_cannot_retry_every_frame() -> None:
    """Refunding the emission must not create an unbounded retry.

    The pre-fix code charged a refusal, which bounded it at ``max_emissions``.
    Giving the allowance back without also spending the dwell clock would let a
    standing refusal re-attempt on every eligible frame.
    """
    # Arrange
    bus = _DenyingBus()
    obs = _observer(bus)

    # Act: an introduction that is refused, then an immediately-following
    # high-novelty frame.
    first = await _emit(obs, first=True)
    second = await _emit(obs, first=False)

    # Assert
    assert first is False
    assert second is False
    assert bus.opted_in == [True], (
        "the second frame re-attempted immediately; the dwell was refunded too"
    )
    assert _state(obs).proactive_emissions == 0


@pytest.mark.asyncio
async def test_a_handler_that_ran_and_failed_is_not_a_delivery() -> None:
    """A KNOWN failure refunds. A ``None`` envelope does not -- that is
    no-subscriber OR a timeout, and a timed-out handler may still compose the
    DM, so refunding on it risks a second proactive message about one frame."""
    # Arrange
    failed = _observer(_AllowingBus(result=SimpleNamespace(success=False, error="boom")))
    silent = _observer(_AllowingBus(result=None))

    # Act
    failed_delivered = await _emit(failed)
    silent_delivered = await _emit(silent)

    # Assert
    assert failed_delivered is False
    assert _state(failed).proactive_emissions == 0
    assert silent_delivered is True, (
        "an unknown outcome must not be treated as a known non-delivery"
    )
    assert _state(silent).proactive_emissions == 1
