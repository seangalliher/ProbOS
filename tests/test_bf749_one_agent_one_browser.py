"""BF-749: an agent gets one browser, not one browser per tool call.

Observed live on 2026-08-11. A single Captain question sent to
``counselor_counselor_0_67c601cb`` launched four Chromium instances, at
11:05:57, 11:06:17, 11:06:21 and 11:06:24 — one per browser tool call, all on
the same host.

The cause was the session resolution order in ``BrowserTool.invoke``:

    1. ``params["session_id"]``          -- the agent named one
    2. ``context["browser_session_id"]`` -- AD-1158 Captain workstation binding
    3. ``uuid.uuid4().hex``              -- **a fresh Chromium**

The Captain had no workstation bound, and the agent never threaded the id it
was handed back from call one into call two. So every call fell to (3).

Omitting ``session_id`` is the path of least resistance when a model fills in a
tool call — the field is optional and the schema described leaving it out as
"create a fresh one", which reads like the *normal* choice. The cost was not
only four processes: ``goto`` in one browser then ``extract_text`` in another
cannot read the page the first one loaded, so the agent's own work did not
compose.

The fix adds a fourth resolution step *before* minting: the agent's own live
session. The AD-1158 binding still outranks it, because a workstation the
Captain is watching is a deliberate target.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.events import EventType
from probos.tools.browser.tool import BrowserTool

from tests.test_ad706_browser_tool import _FakePage, _make_session_factory


def _make_tool() -> tuple[BrowserTool, list[tuple[Any, Any]]]:
    """A real ``BrowserTool`` with a real ``BrowserSession`` whose ``start`` is
    stubbed. Session bookkeeping — expiry, reuse, close — is therefore the
    shipped code, which is the part under test."""
    events: list[tuple[Any, Any]] = []
    tool = BrowserTool(
        config=BrowserToolConfig(enabled=True),
        emit_event=lambda et, data: events.append((et, data)),
    )
    tool._session_factory = _make_session_factory(page=_FakePage(title="T"))
    return tool, events


def _opened(events: list[tuple[Any, Any]]) -> list[str]:
    return [
        d["session_id"]
        for et, d in events
        if et is EventType.BROWSER_SESSION_OPENED
    ]


async def _session_of(tool: BrowserTool, agent_id: str, **ctx: Any) -> str:
    """Invoke a read-only action and report which browser served it."""
    result = await tool.invoke({"action": "state"}, {"agent_id": agent_id, **ctx})
    return str((result.metadata or {}).get("session_id") or "")


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_four_calls_from_one_agent_open_one_browser() -> None:
    """The live incident, reproduced at the tool boundary.

    Four calls, no ``session_id`` on any of them — exactly what the model sent.
    Before the fix this asserted 4 distinct sessions.
    """
    tool, events = _make_tool()

    for _ in range(4):
        await tool.invoke({"action": "state"}, {"agent_id": "counselor_0"})

    assert len(_opened(events)) == 1, (
        f"one agent, four calls, {len(_opened(events))} Chromium launches"
    )
    assert len(tool._sessions) == 1


@pytest.mark.asyncio
async def test_the_second_call_reads_the_page_the_first_one_loaded() -> None:
    """Continuity is the reason this matters more than process count: work
    split across two browsers does not compose."""
    tool, _events = _make_tool()

    first = await _session_of(tool, "a1")
    second = await _session_of(tool, "a1")

    assert first and first == second


# ---------------------------------------------------------------------------
# What must still outrank it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_explicitly_named_session_still_wins() -> None:
    """Naming a session is deliberate; an agent may be working several."""
    tool, events = _make_tool()

    await tool.invoke({"action": "state"}, {"agent_id": "a1"})
    await tool.invoke(
        {"action": "state", "session_id": "named-2"}, {"agent_id": "a1"},
    )

    assert "named-2" in _opened(events)


@pytest.mark.asyncio
async def test_the_captain_binding_outranks_the_agents_own_session() -> None:
    """AD-1158: a workstation the Captain is watching is a deliberate target,
    and it must not be displaced by the agent's earlier private session."""
    tool, _events = _make_tool()

    own = await _session_of(tool, "a1")
    bound = await _session_of(tool, "a1", browser_session_id="ws-42")

    assert bound == "ws-42"
    assert bound != own


@pytest.mark.asyncio
async def test_two_agents_never_share_a_browser() -> None:
    """The claim is per-agent. Sharing would let one agent navigate another's
    page out from under it."""
    tool, events = _make_tool()

    a = await _session_of(tool, "a1")
    b = await _session_of(tool, "a2")

    assert a != b
    assert len(_opened(events)) == 2


@pytest.mark.asyncio
async def test_an_anonymous_caller_claims_nothing() -> None:
    """No ``agent_id`` means no owner to claim for; falling back to some other
    caller's browser would be worse than minting one."""
    tool, events = _make_tool()

    await tool.invoke({"action": "state"}, {})
    await tool.invoke({"action": "state"}, {})

    assert len(_opened(events)) == 2
    assert tool._agent_sessions == {}


# ---------------------------------------------------------------------------
# A claim must not outlive the session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_reaped_session_is_not_claimable() -> None:
    """A stale claim is worse than no claim: it resolves to a dead id, misses
    the live-session guard, and mints a fresh browser anyway."""
    tool, _events = _make_tool()

    first = await _session_of(tool, "a1")
    tool._sessions[first]._created_at = 0.0  # older than session_max_duration
    assert await tool.reap_expired() == 1

    assert tool._agent_sessions == {}
    assert await _session_of(tool, "a1") != first


@pytest.mark.asyncio
async def test_a_discarded_session_is_not_claimable() -> None:
    """AD-1161 discards a session whose work was refused; the claim goes with
    it."""
    tool, _events = _make_tool()

    first = await _session_of(tool, "a1")
    await tool._discard_session(first, reason="refused")

    assert tool._agent_sessions == {}
    assert await _session_of(tool, "a1") != first


@pytest.mark.asyncio
async def test_shutdown_clears_every_claim() -> None:
    tool, _events = _make_tool()

    await tool.invoke({"action": "state"}, {"agent_id": "a1"})
    await tool.invoke({"action": "state"}, {"agent_id": "a2"})
    await tool.stop()

    assert tool._agent_sessions == {}


@pytest.mark.asyncio
async def test_the_captain_still_gets_a_fresh_session_each_time_they_open_one() -> None:
    """``open_captain_session`` routes through ``invoke`` with the Captain's
    own ``agent_id``, so the reuse fallback would have caught it — and its
    contract is the opposite: open a FRESH session, of which the Captain may
    hold several.

    Left unhandled this was not merely a duplicate-session question. A refused
    navigation discards the session it created; reusing the previous one meant
    the refusal closed a page the Captain was already sitting on. AD-1161 pins
    that separately; this pins the BF-749 interaction that would break it.
    """
    tool, events = _make_tool()

    first = await tool.open_captain_session("https://good.test")
    second = await tool.open_captain_session("https://other.test")

    assert first["opened"] is True and second["opened"] is True
    assert first["session_id"] != second["session_id"]
    assert len(_opened(events)) == 2


# ---------------------------------------------------------------------------
# The description the model actually reads
# ---------------------------------------------------------------------------

def test_the_schema_no_longer_advertises_a_fresh_browser_as_the_default() -> None:
    """The mechanism only helps if the field description stops recommending the
    behaviour it exists to prevent."""
    tool, _events = _make_tool()
    desc = tool.input_schema["properties"]["session_id"]["description"].lower()

    assert "continue" in desc
    assert "fresh" not in desc
