"""BF-867: ``mouse_button`` has never executed.

The verb is on the agent surface, named in the tool description, listed in the
schema enum, and fails unconditionally. ``BrowserTool.invoke`` reads the
dispatch key out of ``params`` and leaves it there, then hands the SAME dict to
``dispatch_action``. ``_action_mouse_button`` then read ``params.get("action",
"click")`` as its own sub-verb, so it always saw ``"mouse_button"``, the
``"click"`` default was unreachable, and there was no value an agent could send
that both routed to this handler and satisfied it::

    params passed to handler = {'action': 'mouse_button', 'button': 'left'}
      RAISED: ValueError: mouse_button 'action' must be one of: down, up, click

    sending {'action': 'down', ...} routes on action='down':
      ValueError: unknown browser action: down

Why every existing test missed it: they all call ``_action_mouse_button``
DIRECTLY with a dict they build themselves, omitting the dispatch key --
constructing a state the dispatcher can never produce. ``dispatch_action`` is
exercised for ``key_type``, ``state``, ``click``, ``goto`` and ``screenshot``,
and never for ``mouse_button``. Handler tested, gate tested, nothing crossing
the seam: the canonical half-chain.

So every test in this file drives the REAL dispatcher (or ``BrowserTool.invoke``
above it) with the dispatch key present, which is the only shape that can
reproduce the defect.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser.actions import _MOUSE_BUTTONS, _MOUSE_PRESSES, dispatch_action
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool


# ── fakes ─────────────────────────────────────────────────────────


class _RecordingMouse:
    """Exposes ``click`` deliberately (BF-693) so a handler that regressed to
    the coordinate form is caught rather than silently passing on a fake that
    simply lacks the method."""

    def __init__(self) -> None:
        self.moves: list[tuple[int, int]] = []
        self.downs: list[str] = []
        self.ups: list[str] = []
        self.clicks: list[tuple[int, int, str]] = []

    async def move(self, x: int, y: int) -> None:
        self.moves.append((x, y))

    async def down(self, button: str = "left") -> None:
        self.downs.append(button)

    async def up(self, button: str = "left") -> None:
        self.ups.append(button)

    async def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks.append((x, y, button))


class _RecordingKeyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    async def press(self, combo: str) -> None:
        self.pressed.append(combo)


class _CanvasPage:
    """Mouse + keyboard only — the shape of a real Playwright ``Page`` through
    the parts these verbs touch."""

    def __init__(self) -> None:
        self.mouse = _RecordingMouse()
        self.keyboard = _RecordingKeyboard()
        self.evaluated: list[str] = []

    async def evaluate(self, expr: str) -> None:
        self.evaluated.append(expr)

    async def drag_and_drop(self, src: str, dst: str) -> None:
        self.dragged = (src, dst)


def _session(page: Any | None = None) -> BrowserSession:
    session = BrowserSession(
        session_id="s-867",
        agent_id="agent-a",
        config=BrowserToolConfig(enabled=True),
    )
    session._page = _CanvasPage() if page is None else page  # noqa: SLF001
    return session


def _agent_params(**extra: Any) -> dict[str, Any]:
    """The dict production actually forwards: the dispatch key is IN it.

    ``tool.py`` does ``action = params.get("action")`` -- a read, not a pop --
    then ``dispatch_action(session, action, params)`` with the same dict. A test
    that hand-builds a dict without ``action`` is testing a state the dispatcher
    cannot produce, which is exactly how this verb stayed dead.
    """
    return {"action": "mouse_button", **extra}


# ── the headline: it executes at all ──────────────────────────────


@pytest.mark.asyncio
async def test_mouse_button_reaches_the_mouse_through_the_real_dispatcher() -> None:
    session = _session()
    result = await dispatch_action(session, "mouse_button", _agent_params(button="left"))
    mouse = session.page.mouse
    assert mouse.downs == ["left"]
    assert mouse.ups == ["left"]
    assert mouse.clicks == []  # BF-693: never the coordinate form
    assert result == {"session_id": "s-867", "button": "left", "press": "click"}


@pytest.mark.asyncio
async def test_mouse_button_press_down_through_the_real_dispatcher() -> None:
    session = _session()
    result = await dispatch_action(
        session, "mouse_button", _agent_params(button="right", press="down")
    )
    assert session.page.mouse.downs == ["right"]
    assert session.page.mouse.ups == []
    assert result == {"session_id": "s-867", "button": "right", "press": "down"}


@pytest.mark.asyncio
async def test_mouse_button_press_up_through_the_real_dispatcher() -> None:
    session = _session()
    result = await dispatch_action(
        session, "mouse_button", _agent_params(button="middle", press="up")
    )
    assert session.page.mouse.downs == []
    assert session.page.mouse.ups == ["middle"]
    assert result == {"session_id": "s-867", "button": "middle", "press": "up"}


@pytest.mark.asyncio
async def test_the_click_default_is_reachable_when_press_is_omitted() -> None:
    """The default was unreachable for the verb's whole life: ``action`` was
    always present and always ``"mouse_button"``, so ``.get("action", "click")``
    never returned its default."""
    session = _session()
    result = await dispatch_action(session, "mouse_button", _agent_params())
    assert result["press"] == "click"
    assert session.page.mouse.downs == ["left"]
    assert session.page.mouse.ups == ["left"]


# ── refusals name the parameter the agent actually sends ──────────


@pytest.mark.asyncio
async def test_an_invalid_press_is_refused_by_name() -> None:
    session = _session()
    with pytest.raises(ValueError, match="mouse_button 'press'"):
        await dispatch_action(session, "mouse_button", _agent_params(press="tap"))


@pytest.mark.asyncio
async def test_an_invalid_button_is_refused_by_name() -> None:
    session = _session()
    with pytest.raises(ValueError, match="mouse_button 'button'"):
        await dispatch_action(session, "mouse_button", _agent_params(button="thumb"))


@pytest.mark.asyncio
async def test_the_dispatch_key_is_not_accepted_as_a_press_alias() -> None:
    """A lenient ``action`` fallback would re-create the collision and make the
    AD-1179 G2 guard unwritable. ``action`` is the dispatcher's, not the
    handler's."""
    session = _session()
    result = await dispatch_action(
        session, "mouse_button", {"action": "mouse_button", "press": "down"}
    )
    assert result["press"] == "down"


@pytest.mark.asyncio
async def test_no_sub_verb_can_route_here_by_itself() -> None:
    """The control from the BF-867 reproduction: an agent working around the
    refusal by sending ``{'action': 'down'}`` routes on ``down``, which is not a
    verb. ``click`` IS a verb, but it is the element-click action -- it never
    reaches the mouse handle. There was no value that reached the mouse."""
    for sub_verb in ("down", "up"):
        session = _session()
        with pytest.raises(ValueError, match="unknown browser action"):
            await dispatch_action(session, sub_verb, {"action": sub_verb, "button": "left"})

    session = _session()
    with pytest.raises(ValueError, match="click/type requires"):
        await dispatch_action(session, "click", {"action": "click", "button": "left"})
    assert session.page.mouse.downs == []


# ── end to end, through BrowserTool.invoke ────────────────────────


class _BoundTool(BrowserTool):
    """Real ``invoke`` -- gate, tier classification and dispatch -- over a
    pre-made session, so nothing launches Chromium."""

    def __init__(self, session: BrowserSession, **kw: Any) -> None:
        super().__init__(**kw)
        self._bound = session

    async def _get_or_create_session(self, *_a: object, **_k: object) -> BrowserSession:
        return self._bound


@pytest.mark.asyncio
async def test_browser_tool_invoke_presses_the_mouse_end_to_end() -> None:
    session = _session()
    tool = _BoundTool(session, config=BrowserToolConfig(enabled=True))
    result = await tool.invoke(
        {"action": "mouse_button", "button": "right", "press": "down"},
        context={"agent_id": "agent-a"},
    )
    assert result.error is None, result.error
    assert session.page.mouse.downs == ["right"]
    assert result.output["press"] == "down"


@pytest.mark.asyncio
async def test_browser_tool_invoke_click_default_end_to_end() -> None:
    session = _session()
    tool = _BoundTool(session, config=BrowserToolConfig(enabled=True))
    result = await tool.invoke(
        {"action": "mouse_button"}, context={"agent_id": "agent-a"}
    )
    assert result.error is None, result.error
    assert session.page.mouse.downs == ["left"]
    assert session.page.mouse.ups == ["left"]


# ── the BF-706 siblings keep working ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verb,extra,check",
    [
        ("mouse_move", {"x": 5, "y": 7}, lambda p: p.mouse.moves == [(5, 7)]),
        ("key_combo", {"keys": ["Control", "f"]}, lambda p: p.keyboard.pressed == ["Control+f"]),
        ("scroll", {"direction": "down", "amount": 100}, lambda p: p.evaluated == ["window.scrollBy(0, 100)"]),
        (
            "drag",
            {"from_selector": "#a", "to_selector": "#b"},
            lambda p: p.dragged == ("#a", "#b"),
        ),
    ],
)
async def test_the_bf706_siblings_still_dispatch(
    verb: str, extra: dict[str, Any], check: Any
) -> None:
    session = _session()
    await dispatch_action(session, verb, {"action": verb, **extra})
    assert check(session.page)


# ── the vocabularies are declared once and offered ────────────────


def test_press_is_declared_in_the_schema_from_the_constant() -> None:
    props = BrowserTool(config=BrowserToolConfig(enabled=True)).input_schema["properties"]
    assert props["press"]["enum"] == list(_MOUSE_PRESSES)
    assert props["button"]["enum"] == list(_MOUSE_BUTTONS)


def test_the_mouse_vocabularies_are_ordered_tuples() -> None:
    """Not sets: string hashing is randomised per process, so a set-derived
    enum would emit different wire bytes on different boots."""
    assert isinstance(_MOUSE_BUTTONS, tuple)
    assert isinstance(_MOUSE_PRESSES, tuple)
