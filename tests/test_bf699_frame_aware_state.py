"""BF-699: ``state`` sees inside iframes, because it reads the accessibility tree.

BF-692 gave ``state`` a real DOM walk and it works — on the TOP FRAME ONLY.
``page.evaluate`` runs in the main frame's context, so an application hosting
its editor in an iframe returns exactly one record: the ``<iframe>`` element.

Measured 2026-07-31 against the reference vessel's live Word Online document:
the DOM walk returned one node while the accessibility tree held 700+, every
one behind a single frame boundary (refs ``f1e1`` … ``f1e705``). The agent,
handed an empty list, concluded the document was "rendered as a canvas/image"
and spent its whole budget on that wrong inference. It had no way to reach a
better one — nothing in the tool could say "there is a frame here."

This is not a Word quirk. Word, Excel, PowerPoint, Google Docs and most
embedded SaaS editors are iframe-hosted, so the entire category of application
an operator most wants an agent to drive was silently unreachable.

Four facts were verified against real Chromium before the fix was written, and
are re-asserted here so they cannot rot:

1. ProbOS's own ``_STATE_DOM_WALK_JS`` returns 1 element for a page whose only
   input is one frame down.
2. ``aria_snapshot(mode="ai")`` crosses the boundary unaided and emits
   frame-qualified refs.
3. ARIA role locators do NOT auto-cross — ``page.get_by_role`` finds nothing,
   so the ref, not the role, is what makes this work.
4. ``aria-ref=f1e4`` is itself a valid selector, which is why click / type /
   key_type needed no change at all.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from probos.tools.browser.actions import (
    _A11Y_INTERACTIVE_ROLES,
    _A11Y_SURFACE_ROLES,
    _STATE_MAX_ELEMENTS,
    _a11y_discover_elements,
    _discover_elements,
    _parse_a11y_snapshot,
)

# A snapshot in the exact shape real Chromium emitted for a nested iframe.
_SNAPSHOT = """- generic [active] [ref=e1]:
  - heading "Outer shell" [level=1] [ref=e2]
  - button "Outer Button" [ref=e3]
  - iframe [ref=e4]:
    - generic [active] [ref=f1e1]:
      - heading "Inner document" [level=2] [ref=f1e2]
      - generic [ref=f1e3]:
        - text: Body
        - textbox "Document body" [ref=f1e4]
      - button "Inner Button" [ref=f1e5]
"""


class _Locator:
    def __init__(self, snapshot: Any, *, raises: bool = False) -> None:
        self._snapshot = snapshot
        self._raises = raises
        self.mode_seen: str | None = None

    async def aria_snapshot(self, *, mode: str = "default") -> Any:
        self.mode_seen = mode
        if self._raises:
            raise RuntimeError("snapshot blew up")
        return self._snapshot


class _Page:
    """Minimal page exposing only what BF-699 touches."""

    def __init__(self, snapshot: Any = _SNAPSHOT, *, raises: bool = False) -> None:
        self._locator = _Locator(snapshot, raises=raises)
        self.evaluate_calls = 0

    def locator(self, _selector: str) -> _Locator:
        return self._locator

    async def evaluate(self, _js: str) -> Any:
        self.evaluate_calls += 1
        return {"elements": [{"tag": "button", "selector": "#dom-only"}],
                "matched": 1, "truncated": False}


# ── parsing ───────────────────────────────────────────────────────


def test_it_finds_the_element_one_frame_down() -> None:
    """The headline. The only textbox on the page is inside the iframe."""
    records, _ = _parse_a11y_snapshot(_SNAPSHOT)
    boxes = [r for r in records if r["role"] == "textbox"]
    assert len(boxes) == 1
    assert boxes[0]["name"] == "Document body"
    assert boxes[0]["selector"] == "aria-ref=f1e4"
    assert boxes[0]["frame"] == "f1"


def test_the_selector_is_a_playwright_selector() -> None:
    """Why click/type/key_type needed no change: this string IS a selector.

    ``_resolve_target_selector`` hands ``record["selector"]`` straight to
    ``page.click(...)``, and Playwright resolves ``aria-ref=`` across frames.
    """
    records, _ = _parse_a11y_snapshot(_SNAPSHOT)
    assert all(r["selector"].startswith("aria-ref=") for r in records)


def test_main_frame_elements_report_no_frame() -> None:
    records, _ = _parse_a11y_snapshot(_SNAPSHOT)
    outer = [r for r in records if r["name"] == "Outer Button"]
    assert outer and outer[0]["frame"] == ""
    assert outer[0]["selector"] == "aria-ref=e3"


def test_non_interactive_nodes_are_dropped() -> None:
    """headings, generics, plain text and the iframe shell are not addressable."""
    records, _ = _parse_a11y_snapshot(_SNAPSHOT)
    roles = {r["role"] for r in records}
    assert roles <= (_A11Y_INTERACTIVE_ROLES | _A11Y_SURFACE_ROLES)
    assert "heading" not in roles
    assert "generic" not in roles
    assert "iframe" not in roles


def test_editing_surfaces_are_addressable() -> None:
    """An editing surface is a click target even though it is not a control."""
    snap = '- application "Word Editing" [ref=f1e1]\n- document "Page 1" [ref=f1e9]\n'
    records, _ = _parse_a11y_snapshot(snap)
    assert {r["role"] for r in records} == {"application", "document"}


def test_a_node_without_a_ref_is_skipped() -> None:
    """Unaddressable entries only cost the agent an iteration (BF-692's rule)."""
    records, _ = _parse_a11y_snapshot('- button "No ref here"\n- button "Has" [ref=e2]')
    assert [r["name"] for r in records] == ["Has"]


def test_names_with_escaped_quotes_survive() -> None:
    records, _ = _parse_a11y_snapshot(r'- button "Say \"hi\"" [ref=e1]')
    assert records[0]["name"] == 'Say "hi"'


def test_an_unnamed_control_still_parses() -> None:
    records, _ = _parse_a11y_snapshot("- button [ref=e7]")
    assert records[0]["name"] == ""
    assert records[0]["selector"] == "aria-ref=e7"


def test_the_element_cap_holds_and_reports_the_remainder() -> None:
    snap = "\n".join(f'- button "b{i}" [ref=e{i}]' for i in range(_STATE_MAX_ELEMENTS + 25))
    records, omitted = _parse_a11y_snapshot(snap)
    assert len(records) == _STATE_MAX_ELEMENTS
    assert omitted == 25


def test_an_empty_snapshot_yields_nothing() -> None:
    assert _parse_a11y_snapshot("") == ([], 0)


def test_it_never_surfaces_an_element_value() -> None:
    """BF-692 guarded this for the DOM walk; the new path must not reopen it.

    A password field's ``value`` must never reach the snapshot, because the
    element list goes straight into the agent's context and from there into a
    durable tool trace. The tree records role and accessible NAME only, so this
    holds structurally rather than by redaction — asserted so a later change
    that starts copying values has to break a test to do it.
    """
    snap = (
        '- textbox "Password" [ref=e1]\n'
        '- textbox "Username" [ref=e2]\n'
    )
    records, _ = _parse_a11y_snapshot(snap)
    assert records, "sanity: the fixture should parse"
    for rec in records:
        assert "value" not in rec


@pytest.mark.parametrize("role", sorted(_A11Y_INTERACTIVE_ROLES | _A11Y_SURFACE_ROLES))
def test_every_allowlisted_role_parses(role: str) -> None:
    """A role in the allowlist that the regex cannot match would be dead config."""
    records, _ = _parse_a11y_snapshot(f'- {role} "x" [ref=e1]')
    assert len(records) == 1
    assert records[0]["role"] == role


# ── discovery: degrade to the DOM walk, never past it ─────────────


async def test_the_accessibility_tree_is_preferred_over_the_dom_walk() -> None:
    page = _Page()
    records, _ = await _discover_elements(page)
    assert any(r["selector"] == "aria-ref=f1e4" for r in records)
    assert page.evaluate_calls == 0, "the DOM walk should not have run"


async def test_it_asks_for_the_ai_mode() -> None:
    page = _Page()
    await _a11y_discover_elements(page)
    assert page._locator.mode_seen == "ai"


@pytest.mark.parametrize(
    "snapshot",
    ["", "   ", None, 42, "- heading \"only headings\" [ref=e1]"],
    ids=["empty", "blank", "none", "nonstring", "no-addressable-roles"],
)
async def test_an_unusable_snapshot_falls_through_to_the_dom_walk(snapshot) -> None:
    page = _Page(snapshot)
    records, _ = await _discover_elements(page)
    assert page.evaluate_calls == 1
    assert records == [{"tag": "button", "selector": "#dom-only"}]


async def test_a_raising_snapshot_falls_through_and_warns(caplog) -> None:
    page = _Page(raises=True)
    with caplog.at_level(logging.WARNING, logger="probos.tools.browser.actions"):
        records, _ = await _discover_elements(page)
    assert page.evaluate_calls == 1
    assert records == [{"tag": "button", "selector": "#dom-only"}]
    assert any("BF-699" in r.getMessage() for r in caplog.records)


async def test_a_page_without_aria_snapshot_falls_through() -> None:
    """An older Playwright, or the AD-706 test fake, keeps BF-692 behaviour."""
    class _OldLocator:
        pass

    class _OldPage(_Page):
        def locator(self, _selector: str) -> Any:
            return _OldLocator()

    page = _OldPage()
    records, _ = await _discover_elements(page)
    assert page.evaluate_calls == 1
    assert records == [{"tag": "button", "selector": "#dom-only"}]


async def test_a_page_without_locator_falls_through() -> None:
    class _NoLocator:
        def __init__(self) -> None:
            self.evaluate_calls = 0

        async def evaluate(self, _js: str) -> Any:
            self.evaluate_calls += 1
            return {"elements": [], "matched": 0, "truncated": False}

    page = _NoLocator()
    assert await _a11y_discover_elements(page) is None
    await _discover_elements(page)
    assert page.evaluate_calls == 1


# ── against real Chromium ─────────────────────────────────────────


def _skip_reason_if_no_chromium() -> str | None:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        return f"playwright is not installed: {exc}"
    return None


_NO_CHROMIUM = _skip_reason_if_no_chromium()
real_browser = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=_NO_CHROMIUM or "")

_INNER = (
    "<html><body><h2>Inner document</h2>"
    "<label>Body<input id='inner-input' type='text' aria-label='Document body'></label>"
    "</body></html>"
)
_OUTER = (
    "<html><body><h1>Outer shell</h1>"
    "<button id='outer-btn'>Outer Button</button>"
    f"<iframe id='wac' srcdoc=\"{_INNER}\" width='600' height='300'></iframe>"
    "</body></html>"
)


class _RealPage:
    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self.page: Any = None

    async def __aenter__(self) -> Any:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - environment dependent
            await self._pw.stop()
            self._pw = None
            pytest.skip(f"chromium binary unavailable: {type(exc).__name__}: {exc}")
        self.page = await self._browser.new_page()
        await self.page.set_content(_OUTER)
        return self.page

    async def __aexit__(self, *_exc: Any) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()


@real_browser
async def test_real_the_dom_walk_cannot_see_into_the_iframe() -> None:
    """Fact 1: the premise of the bug, asserted against production JS."""
    from probos.tools.browser.actions import _STATE_DOM_WALK_JS

    async with _RealPage() as page:
        raw = await page.evaluate(_STATE_DOM_WALK_JS)
        found = raw.get("elements") if isinstance(raw, dict) else []
        assert len(found) == 1
        assert found[0].get("selector") == "#outer-btn"


@real_browser
async def test_real_role_locators_do_not_cross_frames_on_their_own() -> None:
    """Fact 3: the ref is what makes this work, not the role."""
    async with _RealPage() as page:
        assert await page.get_by_role("textbox").count() == 0
        assert await page.frame_locator("#wac").get_by_role("textbox").count() == 1


@real_browser
async def test_real_discovery_finds_and_types_into_the_in_frame_element() -> None:
    """The whole fix, end to end, against Chromium.

    Discover through ``_discover_elements``, then drive the resulting selector
    exactly as ``_action_click`` / ``_action_key_type`` would.
    """
    async with _RealPage() as page:
        records, _ = await _discover_elements(page)

        boxes = [r for r in records if r.get("role") == "textbox"]
        assert boxes, "the in-frame textbox was not discovered"
        selector = boxes[0]["selector"]
        assert selector.startswith("aria-ref=")

        # Fact 4: the record's selector goes straight to page.click, unchanged.
        await page.click(selector)
        await page.keyboard.type("Hello World")
        assert await page.locator(selector).input_value() == "Hello World"
