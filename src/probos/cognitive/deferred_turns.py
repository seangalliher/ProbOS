"""AD-1230: a turn the model could not answer waits for the model.

When the LLM endpoint is in a cooldown the Captain's message is not *wrong* and
the agent is not *broken* — the answer is simply unavailable for a few seconds.
BF-714 made the runtime say so honestly ("send that again; this turn will not
retry itself"), which was true but put the recovery work on the Captain for a
condition the ship already knows how to wait out. This module holds the turn and
answers it when the model comes back.

Three things about the shape are load-bearing.

**1. Recovery is polled, never awaited as an event.** ``EventType.
LLM_HEALTH_CHANGED`` looks like the right signal and is not. Its only producer
in ``src/`` is ``LLMClient._health_probe_loop``, which emits only when it found
an unhealthy tier AND its own probe changed the overall status. The common
recovery is an ordinary call succeeding once the cooldown expires — after which
the probe's next tick finds nothing unhealthy and ``continue``s without
emitting. A drain subscribed to that event would therefore strand exactly the
turns it exists to rescue. ``get_health_status()`` is an in-memory read, so
polling it is close to free and is the only reliable signal.

**2. The drain is serial, with a settle delay.** BF-674's finding was that
queued background calls traversing a just-recovered endpoint *amplify* a
transient outage. A queue that replayed in parallel the instant health flipped
would reproduce that defect with more traffic. Turns are replayed oldest-first,
one await at a time, and health is re-read between each — so a re-degrading
endpoint stops the drain rather than being hammered by the rest of the backlog.

**3. One turn per thread, latest wins.** This is a product decision, not a
storage limit. Replaying an entire backlog would deliver several answers at once,
out of order relative to everything the Captain said after them, each written
without sight of the others. A colleague coming back from an interruption
answers where the conversation got to; so does this. The superseded message is
still in the transcript, and the agent reads the thread, so the context is not
lost — only the duplicate answers are.

**The promise this makes must survive the ship.** The queue is in memory,
because the failure it addresses is measured in seconds (BF-674 clocked a 48.8s
proxy window; the live reference case showed 5s tier cooldowns) and a durable
store would outlive its own TTL. So the one hole — a restart while a turn is
held — is closed by ``flush_on_shutdown``, which posts into each waiting thread
rather than dropping a promise the Captain already read. Every abandonment path
here says so in the thread; none is silent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Wording note: every string this module posts is asserted clean against the
# real ``decomposer._CAPABILITY_GAP_RE`` by the test suite. That regex reads a
# reply as "the agent is reporting a capability gap" and routes it into
# self-modification, so a held-turn notice that tripped it would make the
# runtime try to design a new agent every time the proxy hiccuped.
_ANSWER_PREFIX = (
    "Answering your message from {ago} — my language model was degraded when "
    "it arrived.\n\n"
)
_EXPIRED_NOTE = (
    "I did not get back to your message from {ago} before it timed out. The "
    "model stayed degraded for longer than I hold a turn. Send it again if you "
    "still want an answer."
)
_SHUTDOWN_NOTE = (
    "I am restarting with your message from {ago} still held. Send it again "
    "once I am back."
)
_EXHAUSTED_NOTE = (
    "I picked your message from {ago} back up after the model recovered and "
    "still got nothing usable out of it. Send it again if you still want an "
    "answer."
)

# How many times a held turn is re-dispatched before it is abandoned with a
# note. Two, because the first retry covers the ordinary case (the endpoint
# recovered and the call goes through) and a second failure means the recovery
# was not real. An unbounded retry would turn one bad turn into a permanent
# load generator against an endpoint that is already struggling.
_MAX_ATTEMPTS = 2


def _format_ago(seconds: float) -> str:
    """Render an elapsed span the way a person would say it."""
    if seconds < 90.0:
        return "a moment ago"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = seconds / 3600.0
    return f"{hours:.0f} hours ago" if hours >= 1.95 else "about an hour ago"


@dataclass
class DeferredTurn:
    """One Captain message held while the model is down."""

    thread_id: str
    agent_id: str
    params: dict[str, Any]
    queued_at: float
    attempts: int = 0


class DeferredTurnQueue:
    """Holds degraded Captain turns and replays them once the model recovers.

    Collaborators are injected rather than reached for, so the queue is testable
    without a runtime and so the delivery surface stays swappable:

    ``dispatch`` -- ``async (thread_id, agent_id, params) -> str``; re-runs the
    turn and returns the reply text (empty string means it failed again).
    ``post`` -- ``(thread_id, agent_id, body) -> None``; appends into the thread.
    ``is_healthy`` -- ``() -> bool``; True when the model is worth trying.
    """

    def __init__(
        self,
        *,
        dispatch: Callable[[str, str, dict[str, Any]], Awaitable[str]],
        post: Callable[[str, str, str], None],
        is_healthy: Callable[[], bool],
        ttl_seconds: float = 900.0,
        max_threads: int = 16,
        settle_seconds: float = 2.0,
        poll_seconds: float = 5.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dispatch = dispatch
        self._post = post
        self._is_healthy = is_healthy
        self._ttl_seconds = ttl_seconds
        self._max_threads = max_threads
        self._settle_seconds = settle_seconds
        self._poll_seconds = poll_seconds
        self._now = now
        self._held: dict[str, DeferredTurn] = {}
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    # -- admission --------------------------------------------------------

    def offer(self, *, thread_id: str, agent_id: str, params: dict[str, Any]) -> bool:
        """Hold a turn. Returns True only if the caller may promise an answer.

        The return value decides the Captain's wording at the degrade seam, so a
        refusal here must never be silent-dropped into a promise. Refuses after
        ``stop()`` so a turn cannot be admitted into a queue that will never
        drain.
        """
        if self._closed or not thread_id or not agent_id:
            return False
        if thread_id not in self._held and len(self._held) >= self._max_threads:
            logger.warning(
                "AD-1230: holding %d degraded turns already (max_threads=%d); "
                "thread %s is told to resend instead of being promised an answer",
                len(self._held), self._max_threads, thread_id,
            )
            return False
        # Latest wins: a newer message supersedes the one held for this thread.
        self._held[thread_id] = DeferredTurn(
            thread_id=thread_id,
            agent_id=agent_id,
            params=dict(params),
            queued_at=self._now(),
        )
        return True

    def held_count(self) -> int:
        return len(self._held)

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._task is not None:
            return
        self._closed = False
        self._task = asyncio.create_task(self._poll_loop(), name="deferred-turns")

    async def stop(self) -> None:
        """Close admission, drain nothing, and tell every waiting thread."""
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning(
                    "AD-1230: deferred-turn poll loop raised on shutdown",
                    exc_info=True,
                )
        self.flush_on_shutdown()

    def flush_on_shutdown(self) -> None:
        """Post into every held thread instead of dropping a made promise."""
        for entry in list(self._held.values()):
            self._notify(entry, _SHUTDOWN_NOTE)
        self._held.clear()

    # -- draining ---------------------------------------------------------

    async def _poll_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._poll_seconds)
                if not self._held:
                    continue
                self._expire()
                if not self._held or not self._healthy():
                    continue
                # BF-674: let a just-recovered endpoint settle before adding to it.
                await asyncio.sleep(self._settle_seconds)
                await self.drain_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error(
                "AD-1230: deferred-turn poll loop failed; held turns will be "
                "reported at shutdown rather than answered",
                exc_info=True,
            )
            raise

    async def drain_once(self) -> int:
        """Replay held turns oldest-first, one at a time. Returns turns answered."""
        answered = 0
        for entry in sorted(self._held.values(), key=lambda e: e.queued_at):
            if self._closed:
                break
            # Re-read health between turns: a re-degrading endpoint stops the
            # drain rather than taking the rest of the backlog at full rate.
            if not self._healthy():
                break
            if self._held.get(entry.thread_id) is not entry:
                continue  # superseded by a newer message while we awaited
            entry.attempts += 1
            try:
                reply = await self._dispatch(
                    entry.thread_id, entry.agent_id, entry.params
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "AD-1230: replaying the held turn for thread %s raised; it "
                    "keeps its place until attempts run out",
                    entry.thread_id, exc_info=True,
                )
                reply = ""
            if self._held.get(entry.thread_id) is not entry:
                continue  # superseded while dispatching; its answer is stale
            if reply:
                ago = _format_ago(max(0.0, self._now() - entry.queued_at))
                self._deliver(entry, _ANSWER_PREFIX.format(ago=ago) + reply)
                self._held.pop(entry.thread_id, None)
                answered += 1
            elif entry.attempts >= _MAX_ATTEMPTS:
                self._notify(entry, _EXHAUSTED_NOTE)
                self._held.pop(entry.thread_id, None)
        return answered

    def _expire(self) -> None:
        cutoff = self._now() - self._ttl_seconds
        for entry in list(self._held.values()):
            if entry.queued_at <= cutoff:
                self._notify(entry, _EXPIRED_NOTE)
                self._held.pop(entry.thread_id, None)

    # -- delivery ---------------------------------------------------------

    def _healthy(self) -> bool:
        try:
            return bool(self._is_healthy())
        except Exception:
            logger.warning(
                "AD-1230: LLM health read failed; treating the model as still "
                "degraded and leaving held turns in place",
                exc_info=True,
            )
            return False

    def _notify(self, entry: DeferredTurn, template: str) -> None:
        ago = _format_ago(max(0.0, self._now() - entry.queued_at))
        self._deliver(entry, template.format(ago=ago))

    def _deliver(self, entry: DeferredTurn, body: str) -> None:
        try:
            self._post(entry.thread_id, entry.agent_id, body)
        except Exception:
            logger.warning(
                "AD-1230: could not post into thread %s; the text is recorded "
                "here instead: %s",
                entry.thread_id, body[:400], exc_info=True,
            )
