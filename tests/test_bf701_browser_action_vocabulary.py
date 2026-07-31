"""BF-701: the browser tool must admit exactly what it advertises.

AD-1160 built ``key_type`` completely -- the handler, the ``delay_ms``
validation, both tier-2 and tier-3 classification branches, the schema enum
entry, and the description -- and then missed the one set that admits an action
into ``invoke()``. The tool advertised a "12-action vocabulary", listed twelve
in its schema, and accepted eleven.

Nothing caught it because every existing test drives an action it already knows
works. The contradiction only surfaces when you compare the tool's *promises*
against its *behaviour*, which is what this file does.

It cost a live agent an entire turn. The persisted trace shows it reach the
document surface correctly in two calls, ask for ``key_type``, get told the
action does not exist, and then spend seventeen steps guessing at CSS selectors
and canvas coordinates before reloading the page over its own work.
"""

from __future__ import annotations

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser import actions as browser_actions
from probos.tools.browser.tool import (
    _AGENT_ACTION_SET,
    _AGENT_ACTIONS,
    BrowserTool,
)


def _tool() -> BrowserTool:
    return BrowserTool(config=BrowserToolConfig(enabled=True))


class _GateProbe(BrowserTool):
    """A tool whose session creation is a tripwire.

    The admission check runs BEFORE ``_get_or_create_session``, so an action the
    gate accepts reaches here and an action it refuses never does. Raising
    instead of launching Chromium keeps these tests to milliseconds and means a
    passing run proves the gate's decision rather than a browser's behaviour.
    """

    class Admitted(Exception):
        pass

    async def _get_or_create_session(self, *_args: object, **_kwargs: object):
        raise _GateProbe.Admitted()


async def _gate_verdict(action: str, **params: object) -> str:
    """Return 'admitted', 'refused', or the unexpected error text."""
    tool = _GateProbe(config=BrowserToolConfig(enabled=True))
    try:
        result = await tool.invoke(
            {"action": action, **params}, context={"agent_id": "t"}
        )
    except _GateProbe.Admitted:
        return "admitted"
    error = result.error or ""
    if error.startswith("unknown browser action"):
        return "refused"
    return "admitted"


# ── the headline: promises and behaviour must agree ──────────────


@pytest.mark.asyncio
async def test_every_advertised_action_is_admitted() -> None:
    """THE BF-701 regression.

    Every action the schema offers must get past the gate. Before the fix
    ``key_type`` was offered and refused.
    """
    advertised = _tool().input_schema["properties"]["action"]["enum"]
    refused = [a for a in advertised if await _gate_verdict(a) == "refused"]

    assert refused == [], (
        f"the schema offers {refused} but invoke() rejects them as unknown; "
        "an agent that reads the tool description is told to use an action "
        "the tool then refuses"
    )


@pytest.mark.asyncio
async def test_key_type_is_admitted() -> None:
    """Named explicitly, because this is the one that cost a live turn."""
    assert await _gate_verdict("key_type", text="Hello Ezri") == "admitted"


def test_key_type_is_offered_to_agents() -> None:
    assert "key_type" in _AGENT_ACTIONS
    assert "key_type" in _tool().input_schema["properties"]["action"]["enum"]
    assert "key_type" in _tool().description


# ── the three declarations are one declaration ────────────────────


def test_schema_gate_and_description_share_one_source() -> None:
    """The drift that caused BF-701 is now structurally impossible."""
    tool = _tool()
    assert set(tool.input_schema["properties"]["action"]["enum"]) == _AGENT_ACTION_SET
    for action in _AGENT_ACTIONS:
        assert action in tool.description


def test_the_advertised_count_is_the_real_count() -> None:
    """The description used to say 12 while the gate admitted 11.

    The number is derived now, so it cannot be wrong -- but assert it anyway,
    because a hand-written count is exactly how the original defect read as
    correct to every reviewer.
    """
    tool = _tool()
    assert f"{len(_AGENT_ACTIONS)}-action vocabulary" in tool.description
    assert len(_AGENT_ACTIONS) == len(set(_AGENT_ACTIONS)), "duplicate action"


def test_the_editing_surface_recipe_is_taught() -> None:
    """click-then-key_type is not discoverable from the action list alone.

    The agent had the right instinct and still could not act on it. Saying so
    in the description is cheaper than another lost turn.
    """
    description = _tool().description
    assert "key_type" in description
    assert "focus" in description.lower()


# ── privileged verbs stay unexposed ───────────────────────────────


@pytest.mark.parametrize(
    "privileged",
    ["eval_js", "fill_credential", "upload_file", "download", "compute_use_click"],
)
def test_privileged_handlers_are_not_agent_facing(privileged: str) -> None:
    """Fixing BF-701 must not open the gate to everything registered.

    These have handlers in ``_HANDLERS`` and reach the tool by their own
    entry points. ``classify_action`` puts every one of them at tier 3.
    """
    assert privileged in browser_actions._HANDLERS
    assert privileged not in _AGENT_ACTION_SET
    assert privileged not in _tool().input_schema["properties"]["action"]["enum"]


def test_an_unregistered_action_is_still_rejected() -> None:
    assert "definitely_not_an_action" not in _AGENT_ACTION_SET


@pytest.mark.asyncio
async def test_an_unknown_action_still_fails_closed() -> None:
    assert await _gate_verdict("definitely_not_an_action") == "refused"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "privileged",
    ["eval_js", "fill_credential", "upload_file", "download", "compute_use_click"],
)
async def test_privileged_handlers_are_refused_at_the_gate(privileged: str) -> None:
    """Behavioural half of the exposure guard, not just a set comparison."""
    assert await _gate_verdict(privileged) == "refused"


# ── governance for the newly-admitted verb ────────────────────────


def test_key_type_carries_a_tier() -> None:
    """Admitting an action must not slip it past the tier gate.

    AD-1160 already taught ``classify_action`` about ``key_type``; assert it,
    so a future action cannot be added to the tuple without one.
    """
    import inspect

    source = inspect.getsource(browser_actions.classify_action)
    for action in _AGENT_ACTIONS:
        if action in ("goto",):
            continue
        assert action in source or action in {"click", "type"}, (
            f"{action} is offered to agents but classify_action does not "
            "mention it; it would fall through to the default tier"
        )
