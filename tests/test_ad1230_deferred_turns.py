"""AD-1230: a turn the model could not answer waits for the model.

BF-714 made the degrade reply honest ("send that again; this turn will not retry
itself"). It was true, and it put the recovery work on the Captain for a
condition the ship diagnoses itself and waits out in seconds. This holds the
turn and answers it, which turns that sentence back into a promise -- so every
test here is really about whether the promise is keepable.

The crossing test is ``test_a_degraded_turn_is_held_and_answered_after_recovery``:
the real router seam, the real queue, the real drain. Everything else pins a
single edge of it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.deferred_turns import (
    _ANSWER_PREFIX,
    _EXHAUSTED_NOTE,
    _EXPIRED_NOTE,
    _SHUTDOWN_NOTE,
    DeferredTurnQueue,
    format_ago,
)
from probos.routers.agents import (
    _LLM_DEGRADE_FALLBACK,
    _decline_while_holding,
    _hold_degraded_turn,
    _llm_degrade_message,
)


class _Clock:
    """Injected monotonic clock. Nothing here should depend on wall time."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Harness:
    """A queue with recording collaborators."""

    def __init__(self, *, replies: list[str] | None = None, **kwargs: Any) -> None:
        self.clock = _Clock()
        self.posted: list[tuple[str, str, str]] = []
        self.dispatched: list[str] = []
        self.healthy = True
        self._replies = list(replies or [])

        async def _dispatch(thread_id: str, agent_id: str, params: dict) -> str:
            self.dispatched.append(thread_id)
            if self._replies:
                return self._replies.pop(0)
            return f"answer for {thread_id}"

        def _post(thread_id: str, agent_id: str, body: str) -> None:
            self.posted.append((thread_id, agent_id, body))

        kwargs.setdefault("ttl_seconds", 900.0)
        self.queue = DeferredTurnQueue(
            dispatch=_dispatch,
            post=_post,
            is_healthy=lambda: self.healthy,
            now=self.clock,
            **kwargs,
        )

    def offer(self, thread_id: str, agent_id: str = "ezri") -> bool:
        return self.queue.offer(
            thread_id=thread_id, agent_id=agent_id, params={"text": thread_id}
        )

    def bodies(self) -> list[str]:
        return [b for _, _, b in self.posted]


# ── admission ─────────────────────────────────────────────────────


def test_a_turn_is_held() -> None:
    h = _Harness()
    assert h.offer("t1") is True
    assert h.queue.held_count() == 1


def test_a_thread_already_holding_a_turn_refuses_another() -> None:
    """The Captain's correction to the first build, and it deletes a defect.

    "Latest wins" meant a follow-up silently destroyed the question it followed
    up on -- the only abandonment path here that posted no note, in a design
    whose whole point is that abandonment is never silent.
    """
    h = _Harness()
    assert h.offer("t1") is True
    assert h.queue.offer(
        thread_id="t1", agent_id="ezri", params={"text": "newer"}
    ) is False

    assert h.queue.held_count() == 1
    asyncio.run(h.queue.drain_once())
    # The ORIGINAL question is the one answered.
    assert h.dispatched == ["t1"]
    assert h.posted[0][2].endswith("answer for t1")


def test_held_for_reports_the_wait_and_none_when_free() -> None:
    h = _Harness()
    assert h.queue.held_for("t1") is None
    h.offer("t1")
    h.clock.t += 45.0
    assert h.queue.held_for("t1") == pytest.approx(45.0)
    assert h.queue.held_for("other") is None


def test_at_the_thread_ceiling_a_further_thread_is_refused_not_promised() -> None:
    """A refusal must be visible to the caller, because the caller uses it to
    pick between "I'll answer this" and "send it again". A silent drop here
    would be a false promise.
    """
    h = _Harness(max_threads=2)
    assert h.offer("t1") is True
    assert h.offer("t2") is True
    assert h.offer("t3") is False
    assert h.queue.held_count() == 2


def test_the_ceiling_counts_threads_not_messages() -> None:
    h = _Harness(max_threads=1)
    assert h.offer("t1") is True
    assert h.offer("t1") is False  # already held, not a second slot
    assert h.offer("t2") is False  # ceiling reached
    assert h.queue.held_count() == 1


def test_a_turn_without_a_thread_is_refused() -> None:
    h = _Harness()
    assert h.queue.offer(thread_id="", agent_id="ezri", params={}) is False
    assert h.queue.offer(thread_id="t1", agent_id="", params={}) is False


def test_a_turn_offered_after_stop_is_refused() -> None:
    """Admission closes before the drain does, or a turn can enter a queue that
    will never run again.
    """
    h = _Harness()
    asyncio.run(h.queue.stop())
    assert h.offer("t1") is False


# ── draining ──────────────────────────────────────────────────────


def test_a_held_turn_is_answered_into_its_thread() -> None:
    h = _Harness()
    h.offer("t1")
    assert asyncio.run(h.queue.drain_once()) == 1

    thread_id, author, body = h.posted[0]
    assert thread_id == "t1"
    assert author == "ezri"
    assert body.endswith("answer for t1")
    assert "Answering your message from" in body
    assert h.queue.held_count() == 0


def test_turns_are_replayed_oldest_first() -> None:
    """A conversation is ordered. Replaying newest-first would answer the
    Captain's follow-up before the thing it followed up on.
    """
    h = _Harness()
    h.offer("older")
    h.clock.t += 60.0
    h.offer("newer")

    asyncio.run(h.queue.drain_once())
    assert h.dispatched == ["older", "newer"]


def test_a_redegrading_endpoint_stops_the_drain_instead_of_taking_the_backlog() -> None:
    """BF-674's finding was that queued calls traversing a just-recovered
    endpoint amplify the outage. The rest of the backlog waits.
    """
    h = _Harness()
    h.offer("t1")
    h.clock.t += 10.0
    h.offer("t2")

    checks = [True, False]
    h.queue._is_healthy = lambda: checks.pop(0) if checks else False  # type: ignore[method-assign]

    assert asyncio.run(h.queue.drain_once()) == 1
    assert h.dispatched == ["t1"]
    assert h.queue.held_count() == 1


def test_nothing_is_dispatched_while_the_model_is_still_down() -> None:
    h = _Harness()
    h.offer("t1")
    h.healthy = False

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.dispatched == []
    assert h.queue.held_count() == 1


def test_a_second_empty_reply_abandons_the_turn_with_a_note() -> None:
    """An unbounded retry turns one bad turn into a permanent load generator
    against an endpoint that is already struggling.
    """
    h = _Harness(replies=["", "", "would never be reached"])
    h.offer("t1")

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.queue.held_count() == 1  # first failure keeps its place
    assert h.posted == []

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.queue.held_count() == 0
    assert h.bodies() == [_EXHAUSTED_NOTE.format(ago="a moment ago")]


def test_a_raising_dispatch_is_treated_as_a_failed_attempt_not_a_crash() -> None:
    h = _Harness()

    async def _boom(thread_id: str, agent_id: str, params: dict) -> str:
        raise RuntimeError("proxy exploded")

    h.queue._dispatch = _boom  # type: ignore[method-assign]
    h.offer("t1")

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.queue.held_count() == 1


def test_a_turn_removed_mid_dispatch_does_not_deliver_a_stale_answer() -> None:
    """Its TTL ran out while it was in flight, so the thread has already been
    told the turn was abandoned. Posting the answer too would contradict that.
    """
    h = _Harness()

    async def _dispatch(thread_id: str, agent_id: str, params: dict) -> str:
        h.dispatched.append(thread_id)
        h.queue._held.pop(thread_id, None)
        return "stale answer"

    h.queue._dispatch = _dispatch  # type: ignore[method-assign]
    h.offer("t1")

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.posted == []


def test_a_failing_post_does_not_break_the_drain() -> None:
    h = _Harness()

    def _boom(thread_id: str, agent_id: str, body: str) -> None:
        raise RuntimeError("store is gone")

    h.queue._post = _boom  # type: ignore[method-assign]
    h.offer("t1")
    assert asyncio.run(h.queue.drain_once()) == 1


def test_an_unreadable_health_status_leaves_held_turns_alone() -> None:
    h = _Harness()

    def _boom() -> bool:
        raise RuntimeError("health read failed")

    h.queue._is_healthy = _boom  # type: ignore[method-assign]
    h.offer("t1")

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.queue.held_count() == 1


# ── every abandonment says so ─────────────────────────────────────


def test_an_expired_turn_is_reported_not_dropped() -> None:
    h = _Harness(ttl_seconds=100.0)
    h.offer("t1")
    h.clock.t += 101.0
    h.queue._expire()

    assert h.queue.held_count() == 0
    assert h.bodies() == [_EXPIRED_NOTE.format(ago="2 minutes ago")]


def test_a_turn_inside_its_ttl_is_kept() -> None:
    h = _Harness(ttl_seconds=100.0)
    h.offer("t1")
    h.clock.t += 99.0
    h.queue._expire()
    assert h.queue.held_count() == 1


def test_a_restart_tells_every_waiting_thread_instead_of_dropping_the_promise() -> None:
    """The queue is in memory because the outage it covers lasts seconds. This
    is the one hole that leaves, and it is closed by saying so.
    """
    h = _Harness()
    h.offer("t1")
    h.offer("t2")

    asyncio.run(h.queue.stop())

    assert h.queue.held_count() == 0
    assert sorted(t for t, _, _ in h.posted) == ["t1", "t2"]
    assert all(b == _SHUTDOWN_NOTE.format(ago="a moment ago") for b in h.bodies())


def test_stop_is_safe_without_a_started_loop() -> None:
    h = _Harness()
    asyncio.run(h.queue.stop())


def test_start_then_stop_reaps_the_loop() -> None:
    async def _go() -> None:
        h = _Harness(poll_seconds=0.01)
        h.queue.start()
        h.queue.start()  # idempotent
        await asyncio.sleep(0.02)
        await h.queue.stop()

    asyncio.run(_go())


# ── the wording ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "template", [_ANSWER_PREFIX, _EXPIRED_NOTE, _SHUTDOWN_NOTE, _EXHAUSTED_NOTE]
)
def test_no_posted_string_reads_as_a_capability_gap(template: str) -> None:
    """That regex routes a reply into self-modification. A held-turn notice that
    tripped it would make the runtime try to design a new agent every time the
    proxy hiccuped.
    """
    from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

    rendered = template.format(ago="6 minutes ago")
    assert _CAPABILITY_GAP_RE.search(rendered) is None, rendered


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "a moment ago"),
        (89.0, "a moment ago"),
        (120.0, "2 minutes ago"),
        (3600.0, "about an hour ago"),
        (10800.0, "3 hours ago"),
    ],
)
def test_elapsed_renders_the_way_a_person_would_say_it(
    seconds: float, expected: str
) -> None:
    assert format_ago(seconds) == expected


# ── the router seam ───────────────────────────────────────────────


_COOLING = {
    "overall": "degraded",
    "tiers": {
        "standard": {
            "status": "unreachable",
            "consecutive_failures": 3,
            "endpoint_cooldown_remaining_seconds": 5.0,
        }
    },
}


def _runtime(health: Any, queue: Any = None) -> Any:
    class _Client:
        def get_health_status(self) -> Any:
            return health

    return SimpleNamespace(
        llm_client=_Client() if health is not None else None,
        deferred_turn_queue=queue,
    )


def test_without_a_queue_the_router_keeps_the_bf714_resend_wording() -> None:
    """Flag off is BF-714 exactly. The promise is only made where it is kept."""
    held = _hold_degraded_turn(
        _runtime(_COOLING), agent_id="ezri",
        thread=SimpleNamespace(id="t1"), params={},
    )
    assert held == ""


def test_an_undiagnosable_degrade_is_not_held() -> None:
    """No diagnosis is no evidence that a retry would land differently. The
    Captain gets the generic message rather than a promise resting on nothing.
    """
    h = _Harness()
    held = _hold_degraded_turn(
        _runtime({"overall": "degraded", "tiers": {}}, h.queue),
        agent_id="ezri", thread=SimpleNamespace(id="t1"), params={},
    )
    assert held == ""
    assert h.queue.held_count() == 0
    assert _llm_degrade_message(_runtime({"overall": "degraded", "tiers": {}})) == (
        _LLM_DEGRADE_FALLBACK
    )


def test_a_turn_with_no_thread_is_not_held() -> None:
    h = _Harness()
    assert _hold_degraded_turn(
        _runtime(_COOLING, h.queue), agent_id="ezri", thread=None, params={}
    ) == ""


def test_a_refused_offer_falls_back_to_the_resend_wording() -> None:
    """The queue's admission decision is what picks between the two messages, so
    a refusal must never be able to surface as "I'll answer this later".
    """
    h = _Harness(max_threads=1)
    h.offer("other")
    held = _hold_degraded_turn(
        _runtime(_COOLING, h.queue), agent_id="ezri",
        thread=SimpleNamespace(id="t1"), params={},
    )
    assert held == ""


def test_a_raising_queue_falls_back_to_the_resend_wording() -> None:
    class _Boom:
        def offer(self, **kwargs: Any) -> bool:
            raise RuntimeError("queue exploded")

    assert _hold_degraded_turn(
        _runtime(_COOLING, _Boom()), agent_id="ezri",
        thread=SimpleNamespace(id="t1"), params={},
    ) == ""


def test_the_held_wording_promises_an_answer_and_the_resend_wording_does_not() -> None:
    """The two messages differ by exactly one promise."""
    h = _Harness()
    held = _hold_degraded_turn(
        _runtime(_COOLING, h.queue), agent_id="ezri",
        thread=SimpleNamespace(id="t1"), params={},
    )
    assert "I'll answer it here once the model recovers" in held
    assert "send that again" not in held.lower()
    # Both still carry the diagnosis BF-714 exists to deliver.
    assert "standard recovering in 5s" in held

    resend = _llm_degrade_message(_runtime(_COOLING))
    assert "will not retry" in resend
    assert "I'll answer" not in resend


# ── a held thread takes no new work ───────────────────────────────


def test_a_free_thread_dispatches_normally() -> None:
    h = _Harness()
    assert _decline_while_holding(
        _runtime(_COOLING, h.queue), thread=SimpleNamespace(id="t1")
    ) == ""


def test_no_queue_means_no_decline() -> None:
    assert _decline_while_holding(
        _runtime(_COOLING), thread=SimpleNamespace(id="t1")
    ) == ""
    assert _decline_while_holding(_runtime(_COOLING), thread=None) == ""


def test_a_held_thread_is_declined_and_told_the_new_message_is_not_queued() -> None:
    """A Captain who thought both were waiting would sit through the outage
    expecting two answers.
    """
    h = _Harness()
    h.offer("t1")
    h.clock.t += 180.0

    notice = _decline_while_holding(
        _runtime(_COOLING, h.queue), thread=SimpleNamespace(id="t1")
    )
    assert "still holding your message from 3 minutes ago" in notice
    assert "not queued" in notice
    assert "standard recovering in 5s" in notice


def test_the_decline_still_reads_as_a_decline_without_a_diagnosis() -> None:
    h = _Harness()
    h.offer("t1")
    notice = _decline_while_holding(
        _runtime({"overall": "degraded", "tiers": {}}, h.queue),
        thread=SimpleNamespace(id="t1"),
    )
    assert "still holding your message" in notice
    assert "the model is still down" in notice


def test_a_raising_hold_read_dispatches_rather_than_refusing() -> None:
    """Failing closed here would block a thread on a broken read. The turn is
    dispatched instead, which is the pre-AD-1230 behaviour.
    """

    class _Boom:
        def held_for(self, thread_id: str) -> float | None:
            raise RuntimeError("queue exploded")

    assert _decline_while_holding(
        _runtime(_COOLING, _Boom()), thread=SimpleNamespace(id="t1")
    ) == ""


def test_no_decline_string_reads_as_a_capability_gap() -> None:
    from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

    h = _Harness()
    h.offer("t1")
    for health in (_COOLING, {"overall": "degraded", "tiers": {}}):
        notice = _decline_while_holding(
            _runtime(health, h.queue), thread=SimpleNamespace(id="t1")
        )
        assert _CAPABILITY_GAP_RE.search(notice) is None, notice


def test_a_hold_read_that_is_not_a_number_dispatches_rather_than_gagging() -> None:
    """Found by 22 real failures: treating "not None" as "a hold exists" means
    ANY object blocks the thread -- and a MagicMock runtime returns one from
    every attribute. Blocking an agent on an unreadable value is worse than
    dispatching, so an unexpected type degrades to pre-AD-1230 behaviour.
    """
    from unittest.mock import MagicMock

    for value in (MagicMock(), "600", object(), True, float("nan")):
        class _Q:
            def held_for(self, thread_id: str, _v: Any = value) -> Any:
                return _v

        assert _decline_while_holding(
            _runtime(_COOLING, _Q()), thread=SimpleNamespace(id="t1")
        ) == "", value


def test_the_router_declines_before_it_dispatches() -> None:
    """The whole point of the placement: a blocked thread must not spend an LLM
    call on an endpoint already in cooldown. Pins the order in the handler.

    BF-790 broke this without touching the property. The anchor was the whole
    line ``"if _held_notice else await runtime.intent_bus.send(intent)"``, and
    adding a ``raise_on_denial=True`` keyword wrapped it across three lines, so
    ``str.index`` raised ``ValueError: substring not found``. The decline still
    preceded the send; only the formatting moved.

    Re-anchored on the two call names, which survive reformatting. This remains
    a source scan and is therefore weak -- it proves the two statements appear
    in this order, not that a held thread actually skips the dispatch -- but
    narrowing it is the fix for the brittleness, not for the weakness.
    """
    import inspect

    from probos.routers import agents as agents_router

    src = inspect.getsource(agents_router)
    decline = src.index("_held_notice = _decline_while_holding(")
    send = src.index("runtime.intent_bus.send(", decline)
    assert decline < send


# ── AD-1232: a message sent during the outage is not inert ────────


def test_what_the_captain_said_during_the_outage_reaches_the_replay() -> None:
    """The block's real cost, paid down. The thread refuses new turns AND the
    replay used to carry the conversation as it stood when the model died -- so
    a message sent during the outage was declined at the door and invisible to
    the answer. Both, which is a worse deal than "one at a time".
    """
    h = _Harness()
    h.queue._read_history = lambda tid, since: [  # type: ignore[method-assign]
        {"role": "user", "text": "also check the changelog"},
        {"role": "agent", "text": "(I'm still holding your message...)"},
    ]
    h.queue.offer(
        thread_id="t1", agent_id="ezri",
        params={"text": "which versions?", "session_history": [
            {"role": "user", "text": "morning"},
        ]},
    )

    seen: list[dict] = []

    async def _capture(thread_id: str, agent_id: str, params: dict) -> str:
        seen.append(params)
        return "answer"

    h.queue._dispatch = _capture  # type: ignore[method-assign]
    asyncio.run(h.queue.drain_once())

    assert seen[0]["session_history"] == [
        {"role": "user", "text": "morning"},
        {"role": "user", "text": "also check the changelog"},
        {"role": "agent", "text": "(I'm still holding your message...)"},
    ]
    # The held question itself is unchanged -- it is still what gets answered.
    assert seen[0]["text"] == "which versions?"


def test_the_stored_turn_is_not_mutated_by_a_replay() -> None:
    """A failed attempt keeps its place and is retried. Splicing into the stored
    params would compound the interim history on every attempt.
    """
    h = _Harness(replies=["", "ok"])
    h.queue._read_history = lambda tid, since: [  # type: ignore[method-assign]
        {"role": "user", "text": "and the changelog"},
    ]
    h.queue.offer(thread_id="t1", agent_id="ezri", params={"text": "q"})

    asyncio.run(h.queue.drain_once())
    held = h.queue._held["t1"]
    assert "session_history" not in held.params


def test_a_raising_history_read_costs_context_not_the_answer() -> None:
    h = _Harness()

    def _boom(thread_id: str, since: float) -> list[dict[str, str]]:
        raise RuntimeError("store is gone")

    h.queue._read_history = _boom  # type: ignore[method-assign]
    h.offer("t1")

    assert asyncio.run(h.queue.drain_once()) == 1


@pytest.mark.parametrize("bad", [None, "nope", 42, [], [{"role": "user"}], [None]])
def test_a_malformed_history_read_is_ignored(bad: Any) -> None:
    h = _Harness()
    h.queue._read_history = lambda tid, since: bad  # type: ignore[method-assign]
    h.queue.offer(thread_id="t1", agent_id="ezri", params={"text": "q"})

    seen: list[dict] = []

    async def _capture(thread_id: str, agent_id: str, params: dict) -> str:
        seen.append(params)
        return "answer"

    h.queue._dispatch = _capture  # type: ignore[method-assign]
    asyncio.run(h.queue.drain_once())
    assert seen[0].get("session_history") in (None, [])


def test_the_interim_splice_is_bounded() -> None:
    """The block is per-thread but the Captain can still type. An unbounded
    splice would grow the prompt by however long the outage lasted.
    """
    from probos.cognitive.deferred_turns import _INTERIM_HISTORY_LIMIT

    h = _Harness()
    h.queue._read_history = lambda tid, since: [  # type: ignore[method-assign]
        {"role": "user", "text": f"msg {i}"} for i in range(100)
    ]
    h.queue.offer(thread_id="t1", agent_id="ezri", params={"text": "q"})

    seen: list[dict] = []

    async def _capture(thread_id: str, agent_id: str, params: dict) -> str:
        seen.append(params)
        return "answer"

    h.queue._dispatch = _capture  # type: ignore[method-assign]
    asyncio.run(h.queue.drain_once())

    history = seen[0]["session_history"]
    assert len(history) == _INTERIM_HISTORY_LIMIT
    assert history[-1] == {"role": "user", "text": "msg 99"}  # the newest kept


# ── the crossing test ─────────────────────────────────────────────


def test_a_degraded_turn_is_held_and_answered_after_recovery() -> None:
    """Router seam to delivered answer, with both sides real.

    Every piece of this existed before AD-1230 -- the health read at the degrade
    seam, the recovery signal, the thread append that live-refreshes the HXI.
    What did not exist was anything joining them, which is why the Captain was
    told to resend. This is the join.
    """
    h = _Harness()
    runtime = _runtime(_COOLING, h.queue)

    # 1. The turn comes back empty and the router holds it.
    reply_now = _hold_degraded_turn(
        runtime, agent_id="ezri",
        thread=SimpleNamespace(id="t1"), params={"text": "which versions?"},
    )
    assert reply_now != ""
    assert h.queue.held_count() == 1
    assert h.posted == []  # nothing delivered yet -- the promise is outstanding

    # 2. The model is still down; the turn waits rather than burning a retry.
    h.healthy = False
    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.dispatched == []

    # 2b. A follow-up on the same thread is refused BEFORE any dispatch, and is
    #     told plainly that it is not also queued. The first question survives.
    h.clock.t += 180.0
    follow_up = _decline_while_holding(runtime, thread=SimpleNamespace(id="t1"))
    assert "still holding your message from 3 minutes ago" in follow_up
    assert "not queued" in follow_up
    assert h.queue.held_count() == 1

    # 3. It recovers. The turn is replayed and the answer lands in the thread.
    h.healthy = True
    h.clock.t += 120.0
    assert asyncio.run(h.queue.drain_once()) == 1

    thread_id, author, body = h.posted[0]
    assert (thread_id, author) == ("t1", "ezri")
    assert body == _ANSWER_PREFIX.format(ago="5 minutes ago") + "answer for t1"
    assert h.queue.held_count() == 0

    # 4. The thread is free again.
    assert _decline_while_holding(runtime, thread=SimpleNamespace(id="t1")) == ""
