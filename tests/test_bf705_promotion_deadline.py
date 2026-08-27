"""BF-705: the promotion budget and the chat TTL were measured from different clocks.

AD-1165 promotes a long conversational turn to a background task so the chat TTL
cannot kill it. Both clocks exist; nothing related them.

``IntentBus`` starts the TTL at dispatch — ``wait_for(handler(intent),
timeout=intent.ttl_seconds)``, identically on both the in-process and the NATS
branch. ``promote_to_task_after_seconds`` starts when ``run_with_promotion`` is
reached, roughly 1,600 lines into the handler. Everything between (perceive,
sensorium assembly, episodic recall, browser session binding, contention with
background cognition) was unbudgeted, and on the reference vessel it measured
~29s beside a dream cycle scoring 2,547 notebook entries. A 35s budget therefore
acknowledged a turn at 21:40:04 — four seconds after the Captain had been told at
21:40:00 that the agent did not respond. The work itself completed correctly and
reported into the thread; only the acknowledgement was late.

The invariant that actually governs is ``preamble + budget < ttl_seconds``. These
tests pin the three pieces that make it hold:

* ``perceive`` carries the intent's deadline onto the observation — in the typed
  branch always, and in the dict fallback only when the source dict had it
  (BF-698 / AD-432: that branch invents nothing it was not given);
* ``_effective_promotion_budget`` resolves the budget against what is LEFT of
  that deadline, shrinking only, and never to zero — ``run_with_promotion``
  reads ``<= 0.0`` as "do not promote, await inline", which is the exact
  opposite of what a spent deadline needs;
* the promotion log line reports MEASURED elapsed. It used to print the
  configured value, so every line in the ship's log read back whatever the config
  said and none of them were evidence of anything.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive import turn_promotion
from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    _MIN_PROMOTION_BUDGET_SECONDS,
    _PROMOTION_MARGIN_SECONDS,
    _effective_promotion_budget,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.turn_promotion import _ACK_TEMPLATE, run_with_promotion
from probos.runtime import ProbOSRuntime
from probos.types import IntentDescriptor, IntentMessage
from probos.workforce import WorkItem


# ── harness ───────────────────────────────────────────────────────

# A fixed instant so no test depends on the wall clock. ``now`` is always passed
# explicitly to the helper, which is the reason it accepts one.
_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_LOG_ELAPSED_RE = re.compile(r"after ([\d.]+)s measured \(budget ([\d.]+)s\)")


class _TestAgent(CognitiveAgent):
    agent_type = "test_bf705_agent"
    _handled_intents = {"test"}
    instructions = "You are a test agent."
    intent_descriptors = [
        IntentDescriptor(name="test", params={}, description="Test", tier="domain")
    ]


class _FakeWorkItemStore:
    """Backed by the REAL ``WorkItem`` so a bad field name raises here."""

    def __init__(self) -> None:
        self.created: list[WorkItem] = []

    async def create_work_item(self, **kwargs):
        item = WorkItem(status="open", **kwargs)
        self.created.append(item)
        return item

    async def transition_work_item(self, work_item_id, new_status, source="system"):
        return None


class _FakeThreadStore:
    def __init__(self) -> None:
        self.appended: list[dict] = []

    # AD-1274: the promoted-report path posts through
    # ``append_message_once``. A double offering only the older method is LESS
    # capable than production, so the report silently stops reaching the
    # thread while this test still reads as clean.
    def append_message_once(
        self, thread_id, *, message_id, author_id, role, body,
        created_at=None, metadata=None,
    ):
        self.appended.append({"body": body, "metadata": metadata})
        return SimpleNamespace(id=message_id)

    def append_message(self, thread_id, *, author_id, role, body, metadata=None):
        self.appended.append({"body": body, "metadata": metadata})
        return None


def _runtime():
    return SimpleNamespace(
        work_item_store=_FakeWorkItemStore(),
        chat_thread_store=_FakeThreadStore(),
    )


async def _drain(hold: set) -> None:
    while hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)
        await asyncio.sleep(0)


def _observation(*, ttl, created_at):
    return {"intent": "direct_message", "ttl_seconds": ttl, "created_at": created_at}


def _logged_elapsed_and_budget(caplog) -> tuple[float, float]:
    """The two numbers the promotion log line reports, as floats."""
    for record in caplog.records:
        match = _LOG_ELAPSED_RE.search(record.getMessage())
        if match is not None:
            return float(match.group(1)), float(match.group(2))
    raise AssertionError(
        "no promotion log line found in: "
        + repr([r.getMessage() for r in caplog.records])
    )


# ── the degrade path: no readable deadline means no change at all ──


def test_absent_deadline_keys_return_the_configured_budget() -> None:
    """Every non-chat caller and every producer predating BF-705 lands here."""
    assert _effective_promotion_budget(35.0, {"intent": "proactive_think"}) == 35.0


def test_none_deadline_values_return_the_configured_budget() -> None:
    obs = _observation(ttl=None, created_at=None)
    assert _effective_promotion_budget(35.0, obs, now=_T0) == 35.0


def test_a_string_ttl_returns_the_configured_budget() -> None:
    obs = _observation(ttl="60", created_at=_T0)
    assert _effective_promotion_budget(35.0, obs, now=_T0) == 35.0


def test_a_magicmock_deadline_returns_the_configured_budget() -> None:
    """A MagicMock attribute compares as another MagicMock, not a bool.

    The exact ``type`` check is the boundary that keeps one out of the
    arithmetic — ``isinstance`` alone would not, and the resulting "budget"
    would be a MagicMock passed straight into ``asyncio.wait(timeout=...)``.
    """
    obs = _observation(ttl=MagicMock(), created_at=MagicMock())
    assert _effective_promotion_budget(35.0, obs, now=_T0) == 35.0


def test_a_naive_created_at_returns_the_configured_budget() -> None:
    """Subtracting naive from aware raises; it must not take the turn with it."""
    obs = _observation(ttl=60.0, created_at=datetime(2026, 1, 1, 12, 0, 0))
    assert _effective_promotion_budget(35.0, obs, now=_T0) == 35.0


def test_a_non_dict_observation_returns_the_configured_budget() -> None:
    assert _effective_promotion_budget(35.0, MagicMock(), now=_T0) == 35.0  # type: ignore[arg-type]


# ── the deadline is readable ──────────────────────────────────────


def test_a_slow_preamble_shrinks_the_budget_to_fit_the_deadline() -> None:
    """The measured production case: a 29s preamble under a dream cycle.

    ``min(35, 60 - 29 - 5) == 26`` — nine seconds earlier than configured, which
    is the difference between an acknowledgement at 21:39:55 and one at 21:40:04.
    """
    obs = _observation(ttl=60.0, created_at=_T0)
    budget = _effective_promotion_budget(
        35.0, obs, now=_T0 + timedelta(seconds=29),
    )
    assert budget == pytest.approx(26.0)


def test_a_fresh_intent_leaves_the_budget_untouched() -> None:
    """min(35, 60 - 0 - 5) == 35 — an ample deadline changes nothing."""
    obs = _observation(ttl=60.0, created_at=_T0)
    assert _effective_promotion_budget(35.0, obs, now=_T0) == pytest.approx(35.0)


def test_a_huge_ttl_still_returns_the_configured_budget() -> None:
    """Shrinking only. The deadline can never RAISE the configured budget."""
    obs = _observation(ttl=86_400.0, created_at=_T0)
    budget = _effective_promotion_budget(
        35.0, obs, now=_T0 + timedelta(seconds=1),
    )
    assert budget == pytest.approx(35.0)


# ── the deadline is already spent ─────────────────────────────────


def test_an_expired_deadline_clamps_to_the_positive_floor() -> None:
    """The test that proves promotion is not silently DISABLED when it matters.

    ``min(35, 60 - 120 - 5) == -65``. ``run_with_promotion`` reads any
    ``promote_after_seconds <= 0.0`` as "do not promote, await inline" — so
    returning that number would hold the turn inline under a TTL that has
    already fired, guaranteeing the exact failure this BF exists to remove.
    """
    obs = _observation(ttl=60.0, created_at=_T0)
    budget = _effective_promotion_budget(
        35.0, obs, now=_T0 + timedelta(seconds=120),
    )
    assert budget == pytest.approx(_MIN_PROMOTION_BUDGET_SECONDS)
    assert budget > 0.0


def test_the_floor_never_raises_a_budget_above_the_configured_value() -> None:
    """A configured budget under the floor is clamped to itself, not to 1.0."""
    obs = _observation(ttl=60.0, created_at=_T0)
    budget = _effective_promotion_budget(
        0.5, obs, now=_T0 + timedelta(seconds=120),
    )
    assert budget == pytest.approx(0.5)
    assert budget > 0.0


def test_an_off_budget_stays_off_even_with_an_expired_deadline() -> None:
    """0.0 is the shipped default and means OFF. The clamp must not arm it."""
    obs = _observation(ttl=60.0, created_at=_T0)
    assert _effective_promotion_budget(
        0.0, obs, now=_T0 + timedelta(seconds=120),
    ) == 0.0
    assert _effective_promotion_budget(0.0, obs, now=_T0) == 0.0


# ── perceive carries the deadline ─────────────────────────────────


async def test_perceive_carries_the_deadline_from_an_intent_message() -> None:
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=MagicMock(spec=ProbOSRuntime))
    msg = IntentMessage(intent="direct_message", ttl_seconds=45.0)

    obs = await agent.perceive(msg)

    assert obs["ttl_seconds"] == 45.0
    assert obs["created_at"] == msg.created_at
    # And it is readable by the thing that needs it.
    assert _effective_promotion_budget(
        35.0, obs, now=msg.created_at + timedelta(seconds=20),
    ) == pytest.approx(20.0)  # min(35, 45 - 20 - 5)


async def test_perceive_dict_fallback_carries_the_deadline_when_present() -> None:
    """The ~15 agents that call ``self.perceive(intent.__dict__)`` (BF-698)."""
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=MagicMock(spec=ProbOSRuntime))
    msg = IntentMessage(intent="direct_message", ttl_seconds=45.0)

    obs = await agent.perceive(msg.__dict__)

    assert obs["ttl_seconds"] == 45.0
    assert obs["created_at"] == msg.created_at


async def test_perceive_hand_built_dict_does_not_gain_deadline_keys() -> None:
    """AD-432/BF-698: the fallback invents nothing it was not given.

    A hand-built dict has no deadline, and a defaulted one would be a lie about
    a clock that never started — the guard ``TestPerceiveIntentId`` pins for
    ``intent_id`` applies unchanged here.
    """
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=MagicMock(spec=ProbOSRuntime))

    obs = await agent.perceive({"intent": "test", "params": {}, "context": ""})

    assert "ttl_seconds" not in obs
    assert "created_at" not in obs
    assert "intent_id" not in obs  # the AD-432 contract this mirrors
    # And the helper's degrade path is exactly what such an observation gets.
    assert _effective_promotion_budget(35.0, obs) == 35.0


# ── the log line reports a measurement ────────────────────────────


async def test_the_promotion_log_reports_measured_elapsed_not_the_budget(caplog) -> None:
    """A blocked loop makes the real wait overshoot its timeout, visibly.

    This is the production condition in miniature: ``asyncio.wait`` cannot fire
    its timer while a dream cycle holds the loop, so the turn is promoted later
    than the budget says. The old line printed ``promote_after_seconds`` and so
    reported 35.0 for every promotion regardless of what actually happened.
    """
    caplog.set_level(logging.INFO, logger="probos.cognitive.turn_promotion")
    runtime = _runtime()
    hold: set = set()
    release = asyncio.Event()

    async def _work() -> str:
        time.sleep(0.35)  # hold the loop, as concurrent cognition does
        await release.wait()
        return "done"

    try:
        text = await run_with_promotion(
            _work,
            promote_after_seconds=0.01,
            runtime=runtime,
            agent_id="agent-ezri",
            thread_id="thread-1",
            request_text="drive the browser",
            hold=hold,
        )
    finally:
        release.set()
    assert text == _ACK_TEMPLATE.format(work_item_id=runtime.work_item_store.created[0].id)

    measured, budget = _logged_elapsed_and_budget(caplog)
    assert budget == pytest.approx(0.0)  # 0.01 at %.1f
    assert measured >= 0.3
    assert measured != budget

    await _drain(hold)


async def test_the_promotion_log_measures_the_wait_from_the_clock(
    caplog, monkeypatch,
) -> None:
    """The exact value, with the clock controlled rather than raced.

    The module's ``time`` reference is replaced rather than ``time.monotonic``
    patched, so nothing outside this module sees a rewritten clock.
    """
    caplog.set_level(logging.INFO, logger="probos.cognitive.turn_promotion")
    ticks = iter([1000.0, 1042.5])
    monkeypatch.setattr(
        turn_promotion, "time", SimpleNamespace(monotonic=lambda: next(ticks)),
    )
    runtime = _runtime()
    hold: set = set()
    release = asyncio.Event()

    async def _work() -> str:
        await release.wait()
        return "done"

    try:
        await run_with_promotion(
            _work,
            promote_after_seconds=0.01,
            runtime=runtime,
            agent_id="agent-ezri",
            thread_id="thread-1",
            request_text="drive the browser",
            hold=hold,
        )
    finally:
        release.set()

    measured, budget = _logged_elapsed_and_budget(caplog)
    assert measured == pytest.approx(42.5)  # 1042.5 - 1000.0
    assert budget == pytest.approx(0.0)

    await _drain(hold)


# ── end to end: the acknowledgement lands inside the deadline ─────


async def test_a_spent_preamble_still_acknowledges_before_the_deadline() -> None:
    """The whole point, composed the way the call site composes it.

    ``ttl_seconds=8`` with a 6.5s preamble leaves 1.5s. The resolved budget is
    ``max(min(35, 8 - 6.5 - 5), 1.0) == 1.0``, so the acknowledgement lands with
    room to spare under the ``wait_for`` that ``IntentBus`` wraps the handler in.
    """
    obs = _observation(ttl=8.0, created_at=_T0)
    budget = _effective_promotion_budget(35.0, obs, now=_T0 + timedelta(seconds=6.5))
    assert budget == pytest.approx(_MIN_PROMOTION_BUDGET_SECONDS)

    runtime = _runtime()
    hold: set = set()
    release = asyncio.Event()

    async def _work() -> str:
        await release.wait()
        return "the document is written"

    try:
        text = await asyncio.wait_for(
            run_with_promotion(
                _work,
                promote_after_seconds=budget,
                runtime=runtime,
                agent_id="agent-ezri",
                thread_id="thread-1",
                request_text="write the document",
                hold=hold,
            ),
            timeout=1.5,  # what is left of the 8s TTL
        )
        assert text == _ACK_TEMPLATE.format(
            work_item_id=runtime.work_item_store.created[0].id,
        )
    finally:
        release.set()
    await _drain(hold)


async def test_the_unresolved_budget_would_have_missed_that_deadline() -> None:
    """The control. Without BF-705 the same turn is cancelled mid-flight.

    35s of budget against 1.5s of remaining TTL is the defect verbatim: the
    handler is cancelled and the Captain is told the agent did not respond,
    while the run itself was working correctly.
    """
    runtime = _runtime()
    hold: set = set()
    release = asyncio.Event()

    async def _work() -> str:
        await release.wait()
        return "the document is written"

    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                run_with_promotion(
                    _work,
                    promote_after_seconds=35.0,  # the configured value, unresolved
                    runtime=runtime,
                    agent_id="agent-ezri",
                    thread_id="thread-1",
                    request_text="write the document",
                    hold=hold,
                ),
                timeout=1.5,
            )
    finally:
        release.set()
    assert runtime.work_item_store.created == []

    await _drain(hold)


def test_the_margin_and_floor_are_module_constants_not_configuration() -> None:
    """Both are deliberately NOT config fields.

    A knob for either would be a second value to leave misconfigured, which is
    the defect. ``SystemConfig`` is asserted to carry neither so a later change
    that adds one has to come through this test.
    """
    from probos.config import DmAgenticConfig

    assert _PROMOTION_MARGIN_SECONDS == 5.0
    assert _MIN_PROMOTION_BUDGET_SECONDS == 1.0
    fields = set(DmAgenticConfig.model_fields)
    assert "promotion_margin_seconds" not in fields
    assert "min_promotion_budget_seconds" not in fields
