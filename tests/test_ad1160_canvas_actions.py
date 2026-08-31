"""AD-1160 + BF-693: acting on a canvas web app (Word Online).

Word Online draws its document into ``<div id="WACViewPanel">``. There is no
``contenteditable`` and no input element, so every element-scoped browser action
fails there by construction. The primitives that DO work — move the mouse to a
point, click at that point, then ``keyboard.type(text, delay=...)`` — are the
ones AD-1052c's ``BrowserSession.forward_input`` already uses for the *human*
path. The agent path could not reach them:

* **BF-693** — ``mouse_button(action="click")`` clicked viewport ``(0, 0)``
  instead of the current position, because its ``hasattr(mouse, "click_button")``
  guard tested for a method Playwright's ``Mouse`` does not have.
* **AD-1160** — there was no selector-free typing action at all.

Element discovery is deliberately NOT part of this: ``_action_state`` guards on
``hasattr(page, "list_elements")``, which no real Playwright ``Page`` satisfies
(filed as BF-692). These tests exercise the coordinate/focus path that routes
around it.
"""
from __future__ import annotations

import ast
import inspect
import logging
import re
import textwrap
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import _BROWSER_LOOP_ACTIONS
from probos.config import BrowserToolConfig
from probos.tools.browser.actions import (
    _HANDLERS,
    _KEY_TYPE_MAX_DELAY_MS,
    _MOUSE_BUTTONS,
    _action_key_type,
    _action_mouse_button,
    _action_mouse_move,
    _resolve_key_type_delay,
    classify_action,
    dispatch_action,
)
from probos.tools.browser.session import _FORWARD_TEXT_MAX, BrowserSession


# -- Fakes ----------------------------------------------------------------


class _RecordingMouse:
    """Records every call. Deliberately EXPOSES ``click`` so the BF-693 test
    proves the handler stopped calling it, rather than proving the fake lacks
    it — a fake without ``click`` would pass even against the old code."""

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
        self.typed: list[tuple[str, int | None]] = []

    async def type(self, text: str, delay: int | None = None) -> None:
        self.typed.append((text, delay))


class _CanvasPage:
    """A page with only mouse + keyboard — no ``fill``, no ``list_elements``.

    That is the shape of a real Playwright ``Page`` viewed through the parts
    this AD uses, and the shape of Word Online's canvas as far as an agent is
    concerned.
    """

    def __init__(self, *, keyboard: Any | None = None) -> None:
        self.mouse = _RecordingMouse()
        self.keyboard = _RecordingKeyboard() if keyboard is None else keyboard


class _KeyboardlessPage:
    def __init__(self) -> None:
        self.mouse = _RecordingMouse()
        self.keyboard = None


def _make_session(
    *,
    page: Any | None = None,
    config: BrowserToolConfig | None = None,
    last_url: str = "",
) -> BrowserSession:
    """Real ``BrowserSession`` + real ``BrowserToolConfig`` (BF-287)."""
    session = BrowserSession(
        session_id="s-1160",
        agent_id="agent-a",
        config=config or BrowserToolConfig(enabled=True),
    )
    session._page = _CanvasPage() if page is None else page  # noqa: SLF001
    if last_url:
        session.set_last_url(last_url)
    return session


# -- BF-693: mouse_button(click) hits the current position ----------------
#
# BF-867: every call below used to pass ``{"action": "click"}``. That parameter
# is now ``press``. The rename is not cosmetic: ``action`` is the DISPATCH key,
# which ``tool.py`` reads out of ``params`` without removing before forwarding
# the same dict, so the handler always saw ``"mouse_button"`` and refused every
# call. These tests passed only because they call the handler directly with a
# dict they build themselves -- a state the dispatcher cannot produce. The
# crossing test lives in ``tests/test_bf867_mouse_button_dispatch.py``.


@pytest.mark.asyncio
async def test_mouse_button_click_presses_and_releases_without_coordinates() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    result = await _action_mouse_button(session, {"button": "left", "press": "click"})

    assert page.mouse.downs == ["left"]
    assert page.mouse.ups == ["left"]
    assert result == {"session_id": "s-1160", "button": "left", "press": "click"}


@pytest.mark.asyncio
async def test_mouse_button_click_never_calls_click_at_the_origin() -> None:
    """BF-693 regression. Against the pre-fix code this recorded
    ``[(0, 0, "left")]`` — the handler called ``mouse.click(0, 0)`` because
    ``hasattr(mouse, "click_button")`` was always False on a real Playwright
    ``Mouse``, which has no such method."""
    page = _CanvasPage()
    session = _make_session(page=page)

    await _action_mouse_button(session, {"button": "left", "press": "click"})

    assert page.mouse.clicks == []


@pytest.mark.asyncio
async def test_mouse_move_then_click_acts_at_the_moved_position() -> None:
    """The canvas sequence end to end: the click must land where the move put
    the cursor, which is what ``down``/``up`` with no coordinates guarantees."""
    page = _CanvasPage()
    session = _make_session(page=page)

    await _action_mouse_move(session, {"x": 640, "y": 400})
    await _action_mouse_button(session, {"press": "click"})

    assert page.mouse.moves == [(640, 400)]
    assert page.mouse.downs == ["left"] and page.mouse.ups == ["left"]
    assert not any(pos == (0, 0) for pos in page.mouse.moves)
    assert page.mouse.clicks == []


def test_no_handler_references_the_nonexistent_click_button_method() -> None:
    """BF-693's root cause was a guard for a method Playwright does not have.
    Assert the dead branch is gone from the code, not merely unreached — parsed
    as AST so the explanatory comment naming the old API does not count."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(_action_mouse_button)))
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "click_button" not in attributes
    assert "hasattr" not in called
    assert "click" not in attributes


@pytest.mark.asyncio
@pytest.mark.parametrize("button", list(_MOUSE_BUTTONS))
async def test_mouse_button_click_honours_every_valid_button(button: str) -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    await _action_mouse_button(session, {"button": button, "press": "click"})

    assert page.mouse.downs == [button]
    assert page.mouse.ups == [button]


@pytest.mark.asyncio
async def test_mouse_button_down_and_up_are_unchanged_by_the_fix() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    await _action_mouse_button(session, {"button": "right", "press": "down"})
    await _action_mouse_button(session, {"button": "right", "press": "up"})

    assert page.mouse.downs == ["right"]
    assert page.mouse.ups == ["right"]
    assert page.mouse.clicks == []


@pytest.mark.asyncio
async def test_mouse_button_without_a_mouse_handle_raises() -> None:
    class _Handleless:
        mouse = None

    session = _make_session(page=_Handleless())
    with pytest.raises(RuntimeError, match="no mouse handle"):
        await _action_mouse_button(session, {"press": "click"})


# -- AD-1160: key_type happy paths ----------------------------------------


@pytest.mark.asyncio
async def test_key_type_types_at_the_current_focus_with_no_selector() -> None:
    page = _CanvasPage()
    session = _make_session(page=page, last_url="https://example.com/doc")

    result = await _action_key_type(session, {"text": "Hello World"})

    assert page.keyboard.typed == [("Hello World", None)]
    assert result == {
        "session_id": "s-1160",
        "url": "https://example.com/doc",
        "typed": 11,
    }


@pytest.mark.asyncio
async def test_key_type_passes_a_valid_delay_through_to_playwright() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    await _action_key_type(session, {"text": "abc", "delay_ms": 30})

    assert page.keyboard.typed == [("abc", 30)]


@pytest.mark.asyncio
async def test_key_type_omits_the_delay_argument_when_absent() -> None:
    """The no-delay path must stay byte-identical to ``forward_input``'s:
    ``keyboard.type(text)`` with no ``delay`` kwarg at all."""
    calls: list[dict[str, Any]] = []

    class _StrictKeyboard:
        async def type(self, text: str, **kwargs: Any) -> None:
            calls.append({"text": text, "kwargs": kwargs})

    session = _make_session(page=_CanvasPage(keyboard=_StrictKeyboard()))

    await _action_key_type(session, {"text": "abc"})

    assert calls == [{"text": "abc", "kwargs": {}}]


@pytest.mark.asyncio
async def test_key_type_accepts_the_ceiling_delay_exactly() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    await _action_key_type(session, {"text": "x", "delay_ms": _KEY_TYPE_MAX_DELAY_MS})

    assert page.keyboard.typed == [("x", _KEY_TYPE_MAX_DELAY_MS)]


@pytest.mark.asyncio
async def test_key_type_accepts_empty_text() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    result = await _action_key_type(session, {"text": ""})

    assert page.keyboard.typed == [("", None)]
    assert result["typed"] == 0


@pytest.mark.asyncio
async def test_key_type_is_reachable_through_dispatch_action() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    result = await dispatch_action(session, "key_type", {"text": "hi"})

    assert page.keyboard.typed == [("hi", None)]
    assert result["typed"] == 2


# -- AD-1160: key_type delay validation -----------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_delay",
    [
        pytest.param(True, id="bool_true"),
        pytest.param(False, id="bool_false"),
        pytest.param("30", id="str"),
        pytest.param(12.5, id="float"),
        pytest.param([30], id="list"),
        pytest.param(-1, id="negative"),
        pytest.param(_KEY_TYPE_MAX_DELAY_MS + 1, id="over_ceiling"),
        pytest.param(600_000, id="event_loop_stall"),
    ],
)
async def test_key_type_degrades_a_bad_delay_to_no_delay_and_still_types(
    bad_delay: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    with caplog.at_level(logging.WARNING):
        result = await _action_key_type(session, {"text": "abc", "delay_ms": bad_delay})

    assert page.keyboard.typed == [("abc", None)]
    assert result["typed"] == 3
    assert "AD-1160" in caplog.text
    assert "delay_ms" in caplog.text


def test_bool_is_rejected_even_though_python_calls_it_an_int() -> None:
    """``isinstance(True, int)`` is True; ``delay=True`` would reach Playwright
    as a silent 1 ms delay rather than as the malformed value it is."""
    assert isinstance(True, int)
    assert _resolve_key_type_delay(True) is None


@pytest.mark.parametrize("value", [None, 0])
def test_resolve_delay_returns_none_for_the_no_delay_values(value: Any) -> None:
    assert _resolve_key_type_delay(value) is None


@pytest.mark.parametrize("value", [1, 30, _KEY_TYPE_MAX_DELAY_MS])
def test_resolve_delay_returns_valid_delays_unchanged(value: int) -> None:
    assert _resolve_key_type_delay(value) == value


def test_a_zero_delay_is_not_treated_as_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Zero is an explicit "no delay", which is exactly the behaviour — it must
    not be warned about alongside the malformed values."""
    with caplog.at_level(logging.WARNING):
        assert _resolve_key_type_delay(0) is None
    assert "AD-1160" not in caplog.text


def test_the_delay_ceiling_bounds_the_worst_case_event_loop_hold() -> None:
    """An unbounded delay on a bounded string is still unbounded wall time.
    The ceiling is what keeps the worst case finite."""
    assert 0 < _KEY_TYPE_MAX_DELAY_MS <= 250
    worst_case_seconds = _KEY_TYPE_MAX_DELAY_MS * _FORWARD_TEXT_MAX / 1000.0
    assert worst_case_seconds <= 1024.0


# -- AD-1160: key_type error and bound paths ------------------------------


@pytest.mark.asyncio
async def test_key_type_missing_text_raises() -> None:
    session = _make_session()
    with pytest.raises(ValueError, match="key_type requires 'text'"):
        await _action_key_type(session, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_text", [123, ["a"], {"t": "a"}, 1.5, True])
async def test_key_type_non_string_text_raises(bad_text: Any) -> None:
    session = _make_session()
    with pytest.raises(ValueError, match="'text' must be string"):
        await _action_key_type(session, {"text": bad_text})


@pytest.mark.asyncio
async def test_key_type_without_a_keyboard_handle_raises_like_key_combo() -> None:
    """Same condition, same exception type, same message as the sibling
    ``_action_key_combo`` — consistency is the point."""
    session = _make_session(page=_KeyboardlessPage())
    with pytest.raises(RuntimeError, match="no keyboard handle"):
        await _action_key_type(session, {"text": "abc"})


@pytest.mark.asyncio
async def test_key_type_without_a_started_session_raises() -> None:
    session = _make_session()
    session._page = None  # noqa: SLF001
    with pytest.raises(RuntimeError, match="not started"):
        await _action_key_type(session, {"text": "abc"})


@pytest.mark.asyncio
async def test_key_type_bounds_over_long_text_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    page = _CanvasPage()
    session = _make_session(page=page)
    over_long = "x" * (_FORWARD_TEXT_MAX + 500)

    with caplog.at_level(logging.WARNING):
        result = await _action_key_type(session, {"text": over_long})

    typed_text, _delay = page.keyboard.typed[0]
    assert len(typed_text) == _FORWARD_TEXT_MAX
    assert result["typed"] == _FORWARD_TEXT_MAX
    assert result["truncated"] is True
    assert "AD-1160" in caplog.text


@pytest.mark.asyncio
async def test_key_type_at_the_exact_bound_is_not_truncated() -> None:
    page = _CanvasPage()
    session = _make_session(page=page)

    result = await _action_key_type(session, {"text": "x" * _FORWARD_TEXT_MAX})

    assert result["typed"] == _FORWARD_TEXT_MAX
    assert "truncated" not in result


def test_key_type_reuses_the_forward_input_text_bound() -> None:
    """One bound for the human path and the agent path — a second constant
    could drift and let one path burst wider than the other."""
    from probos.tools.browser import actions as actions_module

    assert actions_module._FORWARD_TEXT_MAX is _FORWARD_TEXT_MAX


# -- AD-1160: registration ------------------------------------------------


def test_key_type_is_registered_in_the_handler_table() -> None:
    assert "key_type" in _HANDLERS
    assert _HANDLERS["key_type"] is _action_key_type


def test_registering_key_type_did_not_disturb_the_existing_verbs() -> None:
    for verb in (
        "goto", "state", "click", "type", "scroll", "screenshot", "wait",
        "back", "forward", "extract_text", "drag", "key_combo", "mouse_move",
        "mouse_button", "upload_file", "download", "eval_js",
        "compute_use_click", "fill_credential",
    ):
        assert verb in _HANDLERS, verb


# -- AD-1160: tier classification parity with ``type`` --------------------


def _tier_3_config() -> BrowserToolConfig:
    return BrowserToolConfig(
        enabled=True, tier_3_domain_patterns=["*.bank.example"],
    )


@pytest.mark.parametrize(
    "config_factory, url, expected",
    [
        pytest.param(
            lambda: BrowserToolConfig(enabled=True),
            "https://example.com/doc",
            2,
            id="ordinary_host",
        ),
        pytest.param(
            _tier_3_config,
            "https://secure.bank.example/home",
            3,
            id="tier_3_domain_pattern",
        ),
        pytest.param(
            lambda: BrowserToolConfig(enabled=True),
            "https://shop.example.com/checkout",
            3,
            id="checkout_path_token",
        ),
    ],
)
def test_key_type_is_classified_exactly_as_type_is(
    config_factory: Any, url: str, expected: int,
) -> None:
    """Against the REAL classifier, not a reimplementation of its rules."""
    session = _make_session(config=config_factory(), last_url=url)

    type_tier = classify_action(session, "type", {"text": "x"})
    key_type_tier = classify_action(session, "key_type", {"text": "x"})

    assert type_tier == expected
    assert key_type_tier == type_tier


def test_key_type_is_never_tier_1() -> None:
    """It mutates page state; the silent band is observation only."""
    session = _make_session(last_url="https://example.com/doc")
    assert classify_action(session, "key_type", {"text": "x"}) != 1


def test_key_type_inherits_the_tier_3_element_text_rule_from_the_type_branch() -> None:
    """The element-text rule lives in the branch ``key_type`` now joins, so a
    tier-3 element in the last snapshot escalates it exactly as it does
    ``type``."""
    session = _make_session(last_url="https://example.com/form")
    session.record_state_snapshot(
        [{"index": 0, "selector": "#go", "text": "Confirm order"}]
    )

    assert classify_action(session, "type", {"index": 0, "text": "x"}) == 3
    assert classify_action(session, "key_type", {"index": 0, "text": "x"}) == 3


# -- AD-1160: schema and description ---------------------------------------


def _browser_tool_schema() -> dict[str, Any]:
    from probos.tools.browser.tool import BrowserTool

    return BrowserTool(config=BrowserToolConfig(enabled=True)).input_schema


def _browser_tool_description() -> str:
    from probos.tools.browser.tool import BrowserTool

    return BrowserTool(config=BrowserToolConfig(enabled=True)).description


def test_key_type_is_declared_in_the_tool_action_enum() -> None:
    assert "key_type" in _browser_tool_schema()["properties"]["action"]["enum"]


def test_delay_ms_is_declared_as_an_integer_property() -> None:
    delay = _browser_tool_schema()["properties"]["delay_ms"]
    assert delay["type"] == "integer"
    assert "key_type" in delay["description"]


def test_every_declared_action_has_a_handler() -> None:
    """An advertised action with no handler is an offer the tool cannot keep;
    ``dispatch_action`` would raise ``unknown browser action``."""
    declared = set(_browser_tool_schema()["properties"]["action"]["enum"])
    # ``verify`` is dispatched by BrowserTool.invoke via ``action_verify``
    # rather than through ``_HANDLERS``.
    assert declared - {"verify"} <= set(_HANDLERS)


def test_the_description_action_count_matches_the_schema_enum() -> None:
    """BF-690's lesson: the description was a hand-written second copy of the
    action list and said "10-action vocabulary" while the enum held 11. Pin the
    count to the enum so it cannot drift again."""
    description = _browser_tool_description()
    match = re.search(r"(\d+)-action vocabulary", description)
    assert match is not None, f"no action count in description: {description!r}"
    stated = int(match.group(1))
    declared = _browser_tool_schema()["properties"]["action"]["enum"]
    assert stated == len(declared)


def test_the_description_names_every_action_the_enum_declares() -> None:
    description = _browser_tool_description()
    for action in _browser_tool_schema()["properties"]["action"]["enum"]:
        assert re.search(rf"\b{re.escape(action)}\b", description), action


# -- Out of scope: nothing else moved --------------------------------------


def test_browser_loop_actions_is_byte_identical() -> None:
    """AD-1153/DD-1's fail-safe partition. ``key_type`` is a page-mutating verb
    and must NOT become reachable from the unattended agentic loop as a side
    effect of this AD."""
    assert _BROWSER_LOOP_ACTIONS == frozenset(
        {"goto", "state", "extract_text", "back", "forward", "wait"}
    )
    assert isinstance(_BROWSER_LOOP_ACTIONS, frozenset)
    assert "key_type" not in _BROWSER_LOOP_ACTIONS
    assert "mouse_button" not in _BROWSER_LOOP_ACTIONS


def test_action_state_element_discovery_guard_is_untouched() -> None:
    """BF-692, explicitly out of scope here: ``_action_state`` still guards on
    ``hasattr(page, "list_elements")``. This AD routes AROUND element discovery
    rather than depending on it, so the defect must still be present and
    findable when BF-692 is picked up."""
    from probos.tools.browser.actions import _action_state

    assert 'hasattr(page, "list_elements")' in inspect.getsource(_action_state)
