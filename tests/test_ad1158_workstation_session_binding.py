"""AD-1158: a browser call can be bound to the session the Captain is watching.

The Captain's goal: open a web app in the HXI Browser Workstation, pick a crew
agent, say "type hello world", and watch the agent do it on that page.

Everything needed for that existed except the binding. ``BrowserTool.invoke``
took ``agent_id`` from ``context`` (runtime-owned) but ``session_id`` from
``params`` (agent-supplied), and omitting it creates a **fresh** session:

    session = await self._get_or_create_session(session_id_param, agent_id)

So an instructed agent would open a second, headless page and type into
something the Captain cannot see, while the workstation stream showed nothing
happening.

Putting the id in the agent's prompt would not fix it. That is guidance — the
agent may use it, ignore it, or invent one. AD-1157 (a notebook tag with no
syntax for the classification the standing orders asked for) and BF-688 (a
priority lane the chain never passed) were both the same defect: a mechanism
that existed and was never wired to the caller. The binding therefore lives in
``context``, which the runtime owns and the agent cannot influence.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser.tool import BrowserTool


class _FakeSession:
    """Minimal session standing in for a live page.

    Carries ``_config`` because the AD-706e tier classifier reads it for
    click/type risk assessment — that runs *after* binding, so a thinner fake
    would fail for reasons unrelated to what is under test.
    """

    def __init__(self, session_id: str, config: Any) -> None:
        self.session_id = session_id
        self.last_url = "https://example.com/doc"
        self.agent_id = ""
        self._config = config

    async def state(self, **_kw: Any) -> dict[str, Any]:
        return {"url": self.last_url, "title": "", "screenshot_b64": ""}


class _RecordingTool(BrowserTool):
    """Records what session id reached session resolution.

    Subclassing the real tool keeps ``invoke``'s own logic under test — the
    binding happens inside ``invoke`` before resolution, so a hand-rolled stub
    would test a reimplementation rather than the shipped path.
    """

    def __init__(self) -> None:
        super().__init__(config=BrowserToolConfig(enabled=True))
        self.resolved_with: list[str | None] = []

    async def _get_or_create_session(
        self, session_id: str | None, agent_id: str,
    ) -> Any:
        self.resolved_with.append(session_id)
        return _FakeSession(session_id or "fresh-session", self._config)


async def _invoke(tool: BrowserTool, params: dict, context: dict | None) -> Any:
    return await tool.invoke(params, context)


# ---------------------------------------------------------------------------
# The binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_bound_session_is_used_when_the_agent_names_none() -> None:
    """The defect, stated directly: without this the agent gets a fresh,
    invisible session and the Captain watches an empty stream."""
    tool = _RecordingTool()

    await _invoke(
        tool,
        {"action": "state"},
        {"agent_id": "a1", "browser_session_id": "ws-session-42"},
    )

    assert tool.resolved_with == ["ws-session-42"]


@pytest.mark.asyncio
async def test_an_explicit_session_id_still_wins() -> None:
    """Naming a session is a deliberate act — an agent may be working several.
    The binding supplies a default, it does not override intent."""
    tool = _RecordingTool()

    await _invoke(
        tool,
        {"action": "state", "session_id": "agent-chosen"},
        {"agent_id": "a1", "browser_session_id": "ws-session-42"},
    )

    assert tool.resolved_with == ["agent-chosen"]


@pytest.mark.asyncio
async def test_no_binding_behaves_exactly_as_before() -> None:
    """Every existing caller passes no ``browser_session_id``; those paths must
    be byte-identical."""
    tool = _RecordingTool()

    await _invoke(tool, {"action": "state"}, {"agent_id": "a1"})

    assert tool.resolved_with == [None]


@pytest.mark.asyncio
async def test_absent_context_is_tolerated() -> None:
    tool = _RecordingTool()
    await _invoke(tool, {"action": "state"}, None)
    assert tool.resolved_with == [None]


@pytest.mark.parametrize("bad", ["", None, 0, 123, ["s"], {"id": "s"}, True])
@pytest.mark.asyncio
async def test_a_non_string_binding_is_ignored(bad: object) -> None:
    """The binding is runtime-owned, but a malformed value must degrade to the
    previous behaviour rather than reaching session resolution as a non-str and
    failing somewhere less legible."""
    tool = _RecordingTool()

    await _invoke(
        tool,
        {"action": "state"},
        {"agent_id": "a1", "browser_session_id": bad},
    )

    assert tool.resolved_with == [None]


@pytest.mark.parametrize(
    "action", ["state", "goto", "click", "type", "extract_text", "screenshot"],
)
@pytest.mark.asyncio
async def test_the_binding_applies_to_every_action(action: str) -> None:
    """Binding is a property of the invocation, not of a particular verb — a
    read that resolved to the bound page and a write that did not would be the
    worst possible split."""
    tool = _RecordingTool()

    await _invoke(
        tool,
        {"action": action, "url": "https://example.com", "text": "hi", "selector": "b"},
        {"agent_id": "a1", "browser_session_id": "ws-1"},
    )

    assert tool.resolved_with == ["ws-1"]


@pytest.mark.asyncio
async def test_an_unknown_action_is_still_rejected_before_binding() -> None:
    """The binding must not become a way to reach session creation with an
    invalid verb."""
    tool = _RecordingTool()

    result = await _invoke(
        tool,
        {"action": "sudo_rm"},
        {"agent_id": "a1", "browser_session_id": "ws-1"},
    )

    assert result.error is not None
    assert "unknown browser action" in result.error
    assert tool.resolved_with == []
