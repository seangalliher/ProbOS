"""BF-692: ``state`` must actually discover elements on a real page.

``_action_state`` guarded on ``hasattr(page, "list_elements")``. A real
Playwright ``Page`` has no such method, so against a live browser the handler
fell through to ``[]`` and ``record_state_snapshot([])`` stored an empty
snapshot — element discovery had been inert since AD-706 shipped. Every
existing suite passed because they inject a fake page that DOES implement
``list_elements``: the double was more capable than production.

The tests below are built around that lesson. The ones that matter most
deliberately do NOT provide ``list_elements``, and the real-Chromium section is
the only evidence that production works at all — everything else is a double.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser.actions import (
    _STATE_DOM_WALK_JS,
    _STATE_ELEMENTS_ELISION,
    _STATE_MAX_ELEMENTS,
    _STATE_MAX_SCAN_NODES,
    _discover_elements,
    dispatch_action,
)
from probos.tools.browser.session import BrowserSession

_RECORD_KEYS = frozenset({"role", "text", "tag", "href", "name", "value", "selector"})


# ---------------------------------------------------------------------------
# Doubles — none of which implement ``list_elements``
# ---------------------------------------------------------------------------


class _EvaluatePage:
    """A page shaped like the real thing: ``evaluate``, and no ``list_elements``.

    This is the whole point of the file. Anything that grows a
    ``list_elements`` attribute here is testing the seam, not production.
    """

    def __init__(self, result: Any, *, raises: BaseException | None = None) -> None:
        self._result = result
        self._raises = raises
        self.url = "https://fixture.test/page"
        self.evaluated: list[str] = []
        self.clicked: list[str] = []

    async def evaluate(self, expr: str) -> Any:
        self.evaluated.append(expr)
        if self._raises is not None:
            raise self._raises
        return self._result

    async def click(self, selector: str) -> None:
        self.clicked.append(selector)

    async def title(self) -> str:
        return "Fixture"


class _SeamPage(_EvaluatePage):
    """Same, plus the ``list_elements`` seam, to pin the branch order."""

    def __init__(self, result: Any, seam: list[dict[str, Any]]) -> None:
        super().__init__(result)
        self._seam = seam

    async def list_elements(self) -> list[dict[str, Any]]:
        return list(self._seam)


def _walk_result(
    n: int,
    *,
    matched: int | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    return {
        "elements": [
            {"tag": "button", "role": "button", "text": f"B{i}", "selector": f"#b{i}"}
            for i in range(n)
        ],
        "matched": n if matched is None else matched,
        "truncated": truncated,
    }


def _session(page: Any) -> BrowserSession:
    sess = BrowserSession(
        session_id="s-bf692",
        agent_id="a1",
        config=BrowserToolConfig(enabled=True),
    )
    sess._page = page  # noqa: SLF001 — test seam matches existing browser tests
    return sess


# ---------------------------------------------------------------------------
# Section 1: the real path exists and is reached when no seam is present
# ---------------------------------------------------------------------------


async def test_state_without_list_elements_seam_returns_discovered_elements() -> None:
    """The regression. A page with no ``list_elements`` must still yield a
    non-empty, correctly shaped element list rather than falling through."""
    page = _EvaluatePage(_walk_result(3))
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    elements = out["elements"]
    assert elements, "state produced no elements on a page with no list_elements seam"
    assert len(elements) == 3
    assert page.evaluated == [_STATE_DOM_WALK_JS], "the real DOM walk did not run"
    for i, entry in enumerate(elements):
        assert entry["index"] == i
        assert entry["selector"] == f"#b{i}"
        assert entry["tag"] == "button"
        assert set(entry) - {"index"} <= _RECORD_KEYS


async def test_state_records_the_snapshot_from_the_real_path() -> None:
    page = _EvaluatePage(_walk_result(2))
    sess = _session(page)

    await dispatch_action(sess, "state", {})

    assert sess.resolve_index(0) == {
        "index": 0, "tag": "button", "role": "button", "text": "B0", "selector": "#b0",
    }
    assert sess.resolve_index(1) is not None
    assert sess.resolve_index(2) is None


async def test_state_propagates_only_the_known_record_keys() -> None:
    page = _EvaluatePage(
        {
            "elements": [
                {
                    "tag": "a", "role": "link", "text": "Home", "href": "/home",
                    "name": "nav", "value": "", "selector": "a#home",
                    "unexpected": "dropped",
                },
            ],
            "matched": 1,
            "truncated": False,
        }
    )
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    entry = out["elements"][0]
    assert "unexpected" not in entry
    assert entry["href"] == "/home"
    assert set(entry) == {"index", "tag", "role", "text", "href", "name", "value", "selector"}


async def test_state_with_empty_page_returns_empty_list() -> None:
    page = _EvaluatePage({"elements": [], "matched": 0, "truncated": False})
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    assert out["elements"] == []
    assert sess.resolve_index(0) is None


# ---------------------------------------------------------------------------
# Section 2: the seam still wins, so the existing suites stay honest
# ---------------------------------------------------------------------------


async def test_list_elements_seam_takes_precedence_over_the_real_walk() -> None:
    """Order matters: fake first, real second. Existing suites inject
    ``list_elements`` and must keep getting exactly what they injected."""
    page = _SeamPage(_walk_result(5), [{"tag": "div", "selector": "#seam"}])
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    assert [e["selector"] for e in out["elements"]] == ["#seam"]
    assert page.evaluated == [], "the real walk ran even though the seam was present"


# ---------------------------------------------------------------------------
# Section 3: bounds
# ---------------------------------------------------------------------------


async def test_element_cap_is_enforced_and_truncation_is_marked() -> None:
    over = _STATE_MAX_ELEMENTS + 40
    page = _EvaluatePage(_walk_result(over, matched=over, truncated=True))
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    elements = out["elements"]
    records = [e for e in elements if isinstance(e, dict)]
    assert len(records) == _STATE_MAX_ELEMENTS
    assert elements[-1] == _STATE_ELEMENTS_ELISION.format(omitted=40)


async def test_truncation_marker_is_never_stored_in_the_snapshot() -> None:
    """``resolve_index`` feeds ``_resolve_target_selector``, which calls
    ``record.get()``. A bare string in the snapshot would be an AttributeError
    instead of the honest ``no element at index N``."""
    over = _STATE_MAX_ELEMENTS + 5
    page = _EvaluatePage(_walk_result(over, matched=over, truncated=True))
    sess = _session(page)

    await dispatch_action(sess, "state", {})

    for idx in range(_STATE_MAX_ELEMENTS + 2):
        record = sess.resolve_index(idx)
        assert record is None or isinstance(record, dict)
    assert sess.resolve_index(_STATE_MAX_ELEMENTS) is None


async def test_exactly_at_the_cap_is_not_marked_as_truncated() -> None:
    page = _EvaluatePage(_walk_result(_STATE_MAX_ELEMENTS))
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    assert len(out["elements"]) == _STATE_MAX_ELEMENTS
    assert all(isinstance(e, dict) for e in out["elements"])


async def test_truncated_without_a_usable_matched_count_still_marks_at_least_one() -> None:
    page = _EvaluatePage({"elements": [{"selector": "#a"}], "matched": None, "truncated": True})
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    assert out["elements"][-1] == _STATE_ELEMENTS_ELISION.format(omitted=1)


def test_state_bounds_mirror_the_agentic_loop_bounds() -> None:
    """The cap and the elision text are duplicated across a layer boundary
    (``tools`` must not import ``cognitive``). This is the guard that keeps the
    duplicate from drifting."""
    from probos.cognitive.agentic_dispatch import (
        _BROWSER_ELEMENTS_ELISION,
        _BROWSER_MAX_ELEMENTS,
    )

    assert _STATE_MAX_ELEMENTS == _BROWSER_MAX_ELEMENTS
    assert _STATE_ELEMENTS_ELISION == _BROWSER_ELEMENTS_ELISION


def test_the_walk_bounds_inspection_independently_of_output() -> None:
    """An output cap does not bound the work. A page with a million matching
    nodes must not pay per-node layout reads until the 100th is accepted."""
    assert _STATE_MAX_SCAN_NODES >= _STATE_MAX_ELEMENTS
    assert f"const MAX_SCAN = {_STATE_MAX_SCAN_NODES};" in _STATE_DOM_WALK_JS
    assert f"const MAX_RECORDS = {_STATE_MAX_ELEMENTS};" in _STATE_DOM_WALK_JS


# ---------------------------------------------------------------------------
# Section 4: log-and-degrade
# ---------------------------------------------------------------------------


async def test_evaluate_failure_degrades_to_empty_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    page = _EvaluatePage(None, raises=RuntimeError("page context destroyed"))
    sess = _session(page)

    with caplog.at_level(logging.WARNING, logger="probos.tools.browser.actions"):
        out = await dispatch_action(sess, "state", {})

    assert out["elements"] == []
    assert sess.resolve_index(0) is None
    assert any("BF-692" in rec.message for rec in caplog.records)


@pytest.mark.parametrize(
    "payload",
    [None, [], "elements", {"matched": 3}, {"elements": "nope"}],
    ids=["none", "list", "str", "no-elements-key", "elements-not-a-list"],
)
async def test_malformed_walk_payload_degrades_to_empty(
    payload: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    page = _EvaluatePage(payload)
    sess = _session(page)

    with caplog.at_level(logging.WARNING, logger="probos.tools.browser.actions"):
        out = await dispatch_action(sess, "state", {})

    assert out["elements"] == []
    assert any("BF-692" in rec.message for rec in caplog.records)


async def test_non_dict_entries_in_the_walk_result_are_dropped() -> None:
    page = _EvaluatePage(
        {"elements": [{"selector": "#a"}, "junk", None, {"selector": "#b"}],
         "matched": 4, "truncated": False}
    )
    sess = _session(page)

    out = await dispatch_action(sess, "state", {})

    assert [e["selector"] for e in out["elements"]] == ["#a", "#b"]


async def test_discover_elements_returns_a_pair_on_failure() -> None:
    page = _EvaluatePage(None, raises=ValueError("boom"))

    records, omitted = await _discover_elements(page)

    assert records == []
    assert omitted == 0


# ---------------------------------------------------------------------------
# Section 5: index -> selector resolution off a real-path snapshot
# ---------------------------------------------------------------------------


async def test_click_by_index_resolves_against_a_real_path_snapshot() -> None:
    """The end the bug broke: ``state`` first, then ``click(index=N)``."""
    page = _EvaluatePage(
        {
            "elements": [
                {"tag": "a", "selector": "#first"},
                {"tag": "button", "selector": "form > button:nth-of-type(2)"},
            ],
            "matched": 2,
            "truncated": False,
        }
    )
    sess = _session(page)

    await dispatch_action(sess, "state", {})
    await dispatch_action(sess, "click", {"index": 1})

    assert page.clicked == ["form > button:nth-of-type(2)"]


async def test_click_by_index_beyond_the_snapshot_raises_the_honest_error() -> None:
    page = _EvaluatePage(_walk_result(1))
    sess = _session(page)

    await dispatch_action(sess, "state", {})

    with pytest.raises(ValueError, match="no element at index 7"):
        await dispatch_action(sess, "click", {"index": 7})


# ---------------------------------------------------------------------------
# Section 6: real Chromium — the only tests that can prove production works
# ---------------------------------------------------------------------------

_FIXTURE_HTML = """<!doctype html>
<html><head><title>BF-692 fixture</title></head><body>
  <a href="/one" id="one">One</a>
  <a href="/two">Two</a>
  <button id="go">Go</button>
  <button class="dupe">Dupe A</button>
  <button class="dupe">Dupe B</button>
  <input name="q" placeholder="Search" value="hello">
  <input type="password" name="pw" value="hunter2">
  <textarea name="body">note text</textarea>
  <select name="pick"><option value="a" selected>A</option></select>
  <div role="tab">Tab One</div>
  <div onclick="void 0">Clicky</div>
  <div contenteditable="true" id="doc">Document body</div>
  <div contenteditable="false">Not editable</div>
  <button style="display:none">Display none</button>
  <button style="visibility:hidden">Visibility hidden</button>
  <button style="width:0;height:0;padding:0;border:0;overflow:hidden">Zero size</button>
  <a href="/hidden" hidden>Hidden attribute</a>
</body></html>
"""


def _skip_reason_if_no_chromium() -> str | None:
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        return f"playwright is not installed: {exc}"
    return None


_NO_CHROMIUM = _skip_reason_if_no_chromium()
real_browser = pytest.mark.skipif(
    _NO_CHROMIUM is not None,
    reason=_NO_CHROMIUM or "",
)


class _RealPage:
    """Context manager owning a Chromium page over the static HTML fixture."""

    def __init__(self, tmp_path: Any) -> None:
        self._tmp_path = tmp_path
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
        fixture = self._tmp_path / "bf692.html"
        fixture.write_text(_FIXTURE_HTML, encoding="utf-8")
        await self.page.goto(fixture.as_uri())
        return self.page

    async def __aexit__(self, *_exc: Any) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()


@real_browser
async def test_real_playwright_page_has_no_list_elements_attribute(tmp_path: Any) -> None:
    """The premise of the bug, asserted against the real class."""
    async with _RealPage(tmp_path) as page:
        assert hasattr(page, "list_elements") is False


@real_browser
async def test_real_chromium_walk_finds_the_known_elements(tmp_path: Any) -> None:
    async with _RealPage(tmp_path) as page:
        records, omitted = await _discover_elements(page)

        assert omitted == 0
        assert records, "the DOM walk found nothing on a page full of controls"
        texts = {r.get("text", "") for r in records}
        tags = {r["tag"] for r in records}
        assert {"a", "button", "input", "textarea", "select", "div"} <= tags
        assert {"One", "Two", "Go", "Tab One", "Clicky", "Document body"} <= texts

        by_selector = {r["selector"]: r for r in records}
        assert "#one" in by_selector
        assert by_selector["#one"]["role"] == "link"
        assert by_selector["#one"]["href"] == "/one"
        assert by_selector["#go"]["role"] == "button"
        assert by_selector["#doc"]["role"] == "textbox"


@real_browser
async def test_real_chromium_walk_excludes_hidden_and_zero_size_elements(
    tmp_path: Any,
) -> None:
    async with _RealPage(tmp_path) as page:
        records, _omitted = await _discover_elements(page)

        texts = {r.get("text", "") for r in records}
        for hidden in (
            "Display none", "Visibility hidden", "Zero size", "Hidden attribute",
        ):
            assert hidden not in texts, f"{hidden!r} should not be addressable"
        assert "Not editable" not in texts


@real_browser
async def test_real_chromium_selectors_are_unique_and_resolve_to_one_node(
    tmp_path: Any,
) -> None:
    async with _RealPage(tmp_path) as page:
        records, _omitted = await _discover_elements(page)

        selectors = [r["selector"] for r in records]
        assert selectors, "no selectors were produced"
        assert len(set(selectors)) == len(selectors), "duplicate selectors returned"
        for selector in selectors:
            count = await page.eval_on_selector_all(selector, "els => els.length")
            assert count == 1, f"selector {selector!r} matched {count} nodes"


@real_browser
async def test_real_chromium_walk_never_surfaces_a_password_value(
    tmp_path: Any,
) -> None:
    async with _RealPage(tmp_path) as page:
        records, _omitted = await _discover_elements(page)

        assert not any("hunter2" in str(r.get("value", "")) for r in records)
        pw = [r for r in records if r.get("name") == "pw"]
        assert pw, "the password input was not discovered at all"
        assert pw[0].get("value", "") == ""
        # Non-secret fields still carry their value.
        q = [r for r in records if r.get("name") == "q"]
        assert q and q[0]["value"] == "hello"


@real_browser
async def test_real_chromium_state_then_click_by_index_hits_the_right_node(
    tmp_path: Any,
) -> None:
    """End to end over a real page: the exact sequence the loop runs."""
    async with _RealPage(tmp_path) as page:
        await page.evaluate(
            "() => { document.getElementById('go')"
            ".addEventListener('click', () => { window.__bf692 = 'clicked'; }); }"
        )
        sess = _session(page)

        out = await dispatch_action(sess, "state", {})
        elements = out["elements"]
        target = [e for e in elements if e.get("selector") == "#go"]
        assert target, "the Go button was not in the snapshot"

        await dispatch_action(sess, "click", {"index": target[0]["index"]})

        assert await page.evaluate("() => window.__bf692") == "clicked"


@real_browser
async def test_real_chromium_walk_caps_a_large_page(tmp_path: Any) -> None:
    async with _RealPage(tmp_path) as page:
        await page.set_content(
            "<html><body>"
            + "".join(f'<button id="b{i}">B{i}</button>' for i in range(260))
            + "</body></html>"
        )
        records, omitted = await _discover_elements(page)

        assert len(records) == _STATE_MAX_ELEMENTS
        assert omitted > 0
        assert len({r["selector"] for r in records}) == _STATE_MAX_ELEMENTS


@real_browser
async def test_real_chromium_walk_builds_a_path_selector_when_ids_are_absent(
    tmp_path: Any,
) -> None:
    """Uniqueness cannot lean on ``#id``; the nth-of-type path must carry it."""
    async with _RealPage(tmp_path) as page:
        await page.set_content(
            "<html><body><div><span>x</span>"
            "<button>Alpha</button><button>Beta</button><button>Gamma</button>"
            "</div></body></html>"
        )
        records, _omitted = await _discover_elements(page)

        by_text = {r["text"]: r["selector"] for r in records}
        assert set(by_text) == {"Alpha", "Beta", "Gamma"}
        assert all(re.search(r":nth-of-type\(\d+\)", sel) for sel in by_text.values())
        assert len(set(by_text.values())) == 3
        for text, selector in by_text.items():
            found = await page.eval_on_selector_all(
                selector, "els => els.map(e => e.textContent)"
            )
            assert found == [text]
