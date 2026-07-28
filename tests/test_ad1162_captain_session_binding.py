"""AD-1162: the producer for the session binding AD-1158 reads.

AD-1158 taught ``BrowserTool.invoke`` to read ``context["browser_session_id"]``
so an agent acts on the session the Captain is watching rather than spawning a
fresh, signed-out browser. Nothing outside tests ever *supplied* that key, so
the mechanism was inert: every agent browser call created a new session while
the Captain watched a different one.

That is the sixth instance of one shape in two days -- AD-1157 (classification
field, no caller), BF-688 (priority parameter, no caller), BF-690 (guard armed,
schema still advertised the refused actions), BF-692 (element discovery guards a
Playwright method that does not exist), BF-695 (the whole tool could not start
on Windows). In each the mechanism was correct and tested, and the thing that
would exercise it never did.

These tests pin the PRODUCER, not the reader -- the reader already had AD-1158's
suite and it passed while the feature did nothing.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import _captain_browser_session_id


class _FakeTool:
    """Minimal stand-in exposing only ``list_sessions`` -- the public surface
    ``captain_session_id`` is built on."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_sessions(self) -> list[dict[str, Any]]:
        return list(self._rows)


def _real_property(rows: list[dict[str, Any]]) -> str | None:
    """Drive the REAL ``BrowserTool.captain_session_id`` over ``rows``.

    Binds the unbound property to a stub with the same public surface, so this
    exercises the shipped implementation rather than a reimplementation of it.
    """
    from probos.tools.browser.tool import BrowserTool

    return BrowserTool.captain_session_id.fget(_FakeTool(rows))  # type: ignore[attr-defined]


# -- the property ---------------------------------------------------------


def test_no_sessions_binds_nothing() -> None:
    assert _real_property([]) is None


def test_a_captain_session_is_bound() -> None:
    rows = [{"session_id": "sess-cap", "agent_id": "captain"}]
    assert _real_property(rows) == "sess-cap"


def test_an_agent_owned_session_is_never_bound() -> None:
    """An agent must not silently inherit another agent's browser."""
    rows = [{"session_id": "sess-ezri", "agent_id": "ezri-1"}]
    assert _real_property(rows) is None


def test_only_the_captain_row_is_selected_among_several_owners() -> None:
    rows = [
        {"session_id": "sess-a", "agent_id": "anvil-1"},
        {"session_id": "sess-cap", "agent_id": "captain"},
        {"session_id": "sess-b", "agent_id": "ezri-1"},
    ]
    assert _real_property(rows) == "sess-cap"


def test_the_most_recent_captain_session_wins_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rows = [
        {"session_id": "sess-old", "agent_id": "captain"},
        {"session_id": "sess-new", "agent_id": "captain"},
    ]
    import logging

    with caplog.at_level(logging.WARNING):
        assert _real_property(rows) == "sess-new"
    assert "AD-1162" in caplog.text
    assert "2 live browser sessions" in caplog.text


@pytest.mark.parametrize("bad", [None, "", 42, {"nested": "dict"}, []])
def test_a_malformed_session_id_binds_nothing(bad: Any) -> None:
    rows = [{"session_id": bad, "agent_id": "captain"}]
    assert _real_property(rows) is None


def test_a_row_missing_session_id_binds_nothing() -> None:
    assert _real_property([{"agent_id": "captain"}]) is None


# -- the dispatch-side resolver -------------------------------------------


def test_resolver_returns_none_without_a_browser_tool() -> None:
    """Every runtime predating the browser tool must be unaffected."""
    assert _captain_browser_session_id(SimpleNamespace()) is None
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=None)) is None


def test_resolver_returns_the_bound_session() -> None:
    tool = SimpleNamespace(captain_session_id="sess-cap")
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=tool)) == "sess-cap"


def test_resolver_degrades_when_the_property_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An ambient convenience must never be able to fail a run."""
    import logging

    class _Raising:
        @property
        def captain_session_id(self) -> str:
            raise RuntimeError("session table corrupt")

    with caplog.at_level(logging.WARNING):
        result = _captain_browser_session_id(SimpleNamespace(browser_tool=_Raising()))
    assert result is None
    assert "AD-1162" in caplog.text


@pytest.mark.parametrize("bad", [None, "", 7, object()])
def test_resolver_rejects_a_non_str_binding(bad: Any) -> None:
    tool = SimpleNamespace(captain_session_id=bad)
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=tool)) is None


def test_resolver_tolerates_a_tool_without_the_property() -> None:
    """An older BrowserTool build lacks it; that is honest-degrade, not a crash."""
    assert _captain_browser_session_id(
        SimpleNamespace(browser_tool=SimpleNamespace())
    ) is None
