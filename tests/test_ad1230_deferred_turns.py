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
    _format_ago,
)
from probos.routers.agents import (
    _LLM_DEGRADE_FALLBACK,
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


def test_a_newer_message_supersedes_the_one_held_for_that_thread() -> None:
    """One answer per thread, not a backlog replayed at the Captain. The
    superseded message is still in the transcript and the agent reads the
    thread, so the context survives -- only the duplicate answers do not.
    """
    h = _Harness()
    h.offer("t1")
    h.queue.offer(thread_id="t1", agent_id="ezri", params={"text": "newer"})

    assert h.queue.held_count() == 1
    asyncio.run(h.queue.drain_once())
    assert h.dispatched == ["t1"]


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


def test_the_ceiling_does_not_block_replacing_a_thread_already_held() -> None:
    h = _Harness(max_threads=1)
    assert h.offer("t1") is True
    assert h.offer("t1") is True


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


def test_a_turn_superseded_mid_dispatch_does_not_deliver_a_stale_answer() -> None:
    """The Captain sent a newer message while the old one was in flight. The
    old answer is about a superseded question.
    """
    h = _Harness()

    async def _dispatch(thread_id: str, agent_id: str, params: dict) -> str:
        h.dispatched.append(thread_id)
        h.queue.offer(thread_id="t1", agent_id="ezri", params={"text": "newer"})
        return "stale answer"

    h.queue._dispatch = _dispatch  # type: ignore[method-assign]
    h.offer("t1")

    assert asyncio.run(h.queue.drain_once()) == 0
    assert h.posted == []
    assert h.queue.held_count() == 1


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
    assert _format_ago(seconds) == expected


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

    # 3. It recovers. The turn is replayed and the answer lands in the thread.
    h.healthy = True
    h.clock.t += 300.0
    assert asyncio.run(h.queue.drain_once()) == 1

    thread_id, author, body = h.posted[0]
    assert (thread_id, author) == ("t1", "ezri")
    assert body == _ANSWER_PREFIX.format(ago="5 minutes ago") + "answer for t1"
    assert h.queue.held_count() == 0
