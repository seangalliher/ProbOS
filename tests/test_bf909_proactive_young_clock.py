"""BF-909: the proactive loop on a machine whose monotonic clock is young.

``time.monotonic()`` counts from machine boot, so on a freshly booted CI runner, container or VM it is smaller than the
loop's cooldowns. Two sites in ``probos.proactive`` read "never recorded" as ``0.0`` and compared that with the clock: the
per-agent think cooldown in ``_run_cycle`` (300 s, tripled to 900 s for the first 600 s of the loop's life) and the BF-163
DM-send throttle (60 s). On a young clock a never-recorded agent or pair looked as if it had just been recorded, so a never-recorded
agent was eligible only once the machine's uptime reached the effective cooldown (900 s while the loop is under 600 s old,
300 s after), and the first DM to a target in the first minute was throttled. Both sites
now carry the BF-025 guard (``last > 0``). The canary that exposed it,
``tests/test_ad1343_stop_crossing.py::test_the_proactive_cycle_offers_a_stopped_agent_nothing``, is unchanged.

These tests make the clock young without sleeping. Each says which mutant of the fix it kills.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.crew_profile import CallsignRegistry
from probos.proactive import ProactiveCognitiveLoop
from probos.types import IntentResult
from probos.ward_room import WardRoomService
from tests.fixtures.proactive_clock import FakeClock as _FakeClock
from tests.fixtures.proactive_clock import install_loop_clock
from tests.test_proactive import _make_mock_agent, _make_mock_runtime


@pytest.fixture
def clock_at(monkeypatch: pytest.MonkeyPatch) -> Callable[[float], _FakeClock]:
    """Install a fake monotonic clock, ``start`` seconds after boot, as the one ``probos.proactive`` reads.

    Only the module's own ``time`` name is replaced (see ``tests/fixtures/proactive_clock.py``). Build the loop AFTER
    installing the clock, so the loop's cold-start reference (``_started_at``) is young as well and the BF-039 tripling
    is exercised.
    """

    def install(start: float) -> _FakeClock:
        return install_loop_clock(monkeypatch, start)

    return install


@pytest.fixture
def young_clock(clock_at: Callable[[float], _FakeClock]) -> _FakeClock:
    """A machine 30 s after boot: under both the 60 s DM throttle and the 900 s cold-start cooldown (3 x 300 s)."""
    return clock_at(30.0)


def _crew_world(clock: _FakeClock, *, result: str = "[NO_RESPONSE]") -> tuple[ProactiveCognitiveLoop, Any]:
    """A default-cooldown (300 s) loop over one crew agent, built now: call it after the clock is installed."""
    agent = _make_mock_agent()
    agent.handle_intent.return_value = IntentResult(intent_id="x", agent_id=agent.id, success=True, result=result)
    loop = ProactiveCognitiveLoop(cooldown=300.0)
    loop.set_runtime(_make_mock_runtime(agents=[agent]))
    assert loop._started_at == clock()  # premise: the loop reads the fake clock, so its cold-start window is young too
    return loop, agent


# --- _run_cycle: the per-agent think cooldown (BF-909 site 1) -----------------------------------------------------


@pytest.mark.parametrize("uptime", [0.0, 30.0, 600.0, 899.0, 1200.0])
async def test_run_cycle_never_thought_agent_at_any_uptime_is_offered_a_think(
    clock_at: Callable[[float], _FakeClock], uptime: float,
) -> None:
    """Kills "the guard removed": unguarded, a never-recorded agent is ``monotonic() - 0.0 < 900`` and, in a loop that runs
    a cycle right after it is built (as here), sits in cooldown until the machine is 900 s old. It fails without the guard at 0, 30, 600 and 899 s; 1200 s (past the cooldown) pins
    unchanged behaviour."""
    clock = clock_at(uptime)
    loop, agent = _crew_world(clock)
    assert agent.id not in loop._last_proactive  # premise: it has never thought

    await loop._run_cycle()

    agent.handle_intent.assert_called_once()


async def test_run_cycle_just_thought_agent_on_a_young_clock_stays_in_the_tripled_cooldown_until_it_ends(
    young_clock: _FakeClock,
) -> None:
    """Kills "the guard always passes" (the cooldown would never hold, first cycle) and "no cold-start tripling" (the plain
    300 s cooldown would have ended inside the 400 s step); the last step kills a cooldown that never ends."""
    loop, agent = _crew_world(young_clock)
    loop._last_proactive[agent.id] = young_clock()  # it thought just now, as the clock reads 30 s

    await loop._run_cycle()
    agent.handle_intent.assert_not_called()  # right after a think: in cooldown

    young_clock.advance(400)  # 430 s: 400 s since the think is past 300 s but inside the tripled 900 s (and the 600 s window)
    await loop._run_cycle()
    agent.handle_intent.assert_not_called()

    young_clock.advance(501)  # 931 s: 901 s since the think, past the 900 s cooldown and past the 600 s cold-start window
    await loop._run_cycle()
    agent.handle_intent.assert_called_once()


async def test_run_cycle_real_post_on_a_young_clock_records_the_clock_and_the_next_cycle_honours_it(
    young_clock: _FakeClock,
) -> None:
    """Crosses the seam: the producer (a real think and post writes ``_last_proactive`` from the clock) and the consumer
    (the next cycle's cooldown reads it). Kills a producer that stops writing or writes a value the consumer reads as never
    recorded, and a guard that lets a recorded young-clock stamp through."""
    loop, agent = _crew_world(young_clock, result="The coolant loop on deck four is drifting; I will watch it.")

    await loop._run_cycle()
    agent.handle_intent.assert_called_once()
    assert loop._last_proactive[agent.id] == young_clock()  # the producer wrote the fake clock's reading, 30 s

    young_clock.advance(10)
    await loop._run_cycle()
    agent.handle_intent.assert_called_once()  # 10 s after a real post: in cooldown

    young_clock.advance(901)
    await loop._run_cycle()
    assert agent.handle_intent.call_count == 2  # past the tripled cooldown: it thinks again


async def test_run_cycle_on_an_old_machine_thinks_a_never_thought_agent_and_cools_a_just_thought_one(
    clock_at: Callable[[float], _FakeClock],
) -> None:
    """Unchanged behaviour at about 100000 s of uptime (a machine up for over a day): kills a fix that disturbs the
    old-clock path, either way (a never-thought agent held back, or a just-thought agent let through)."""
    clock = clock_at(100_000.0)
    never = _make_mock_agent(agent_type="architect", agent_id="never")
    just = _make_mock_agent(agent_type="builder", agent_id="just")
    for agent in (never, just):
        agent.handle_intent.return_value = IntentResult(
            intent_id="x", agent_id=agent.id, success=True, result="[NO_RESPONSE]",
        )
    loop = ProactiveCognitiveLoop(cooldown=300.0)
    loop.set_runtime(_make_mock_runtime(agents=[never, just]))
    assert loop._started_at == clock()
    loop._last_proactive["just"] = clock()

    await loop._run_cycle()

    never.handle_intent.assert_called_once()
    just.handle_intent.assert_not_called()


# --- extract_and_execute_dms: the BF-163 DM-send throttle (BF-909 site 2) ------------------------------------------


async def _captain_dm_bodies(ward_room: WardRoomService) -> list[str]:
    """The body of every DM thread in the Ward Room, whoever it is to."""
    bodies: list[str] = []
    for channel in await ward_room.list_channels():
        if channel.channel_type == "dm":
            bodies.extend(thread.body for thread in await ward_room.list_threads(channel.id, limit=500))
    return sorted(bodies)


async def test_extract_and_execute_dms_first_send_on_a_young_clock_passes_and_the_next_within_60s_is_throttled(
    clock_at: Callable[[float], _FakeClock], tmp_path: Path,
) -> None:
    """Kills "the guard removed" (a first DM at 5 s of uptime is ``5 - 0.0 < 60``, throttled), "the guard always passes"
    (the second send inside the window would be delivered) and a throttle that never lifts (the third send)."""
    clock = clock_at(5.0)
    first_body = "Captain, the warp core diagnostics finished clean."
    second_body = "Captain, requesting leave to inspect deck seven tomorrow."  # not similar to the first (AD-614 stays out of the way)
    third_body = "Captain, the long range sensor array needs recalibrating soon."
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ward_room.start()
    try:
        loop = ProactiveCognitiveLoop(cooldown=300.0)
        loop.set_runtime(SimpleNamespace(ward_room=ward_room, callsign_registry=CallsignRegistry()))
        sender = SimpleNamespace(id="agent-bf909-sender", agent_type="counselor", callsign="Troi")
        pair_key = f"{sender.id}:captain"

        _, first = await loop.extract_and_execute_dms(sender, f"[DM @captain] {first_body} [/DM]")
        assert [action["type"] for action in first] == ["dm"]  # a first DM, 5 s after boot, is not throttled
        assert loop._dm_send_cooldowns[pair_key] == clock()  # premise: the send recorded the fake clock's reading, 5 s
        assert await _captain_dm_bodies(ward_room) == [first_body]

        clock.advance(10)  # 15 s after boot, 10 s after the send: inside the 60 s throttle
        _, second = await loop.extract_and_execute_dms(sender, f"[DM @captain] {second_body} [/DM]")
        assert second == []
        assert await _captain_dm_bodies(ward_room) == [first_body]  # the throttled DM's text never reached the Ward Room

        clock.advance(61)  # 76 s after boot, 71 s after the send: the throttle has lifted
        _, third = await loop.extract_and_execute_dms(sender, f"[DM @captain] {third_body} [/DM]")
        assert [action["type"] for action in third] == ["dm"]
        assert await _captain_dm_bodies(ward_room) == sorted([first_body, third_body])
    finally:
        await ward_room.stop()
