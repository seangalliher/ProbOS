"""BF-762 (#1220): the container ration, not the allowance, starved a JSON array.

BF-761 (#1219) made `render_tool_output` SEARCH for the largest per-leaf
allowance that fits, taking real documentation from 3% of the budget to
97-100%. It did nothing about the other dimension, and on an array that
dimension is the binding one: `_LIST_KEEP = 8` rations the list to eight
entries whatever the allowance, so raising the allowance changes nothing and
the search correctly stops.

Measured before this fix, 120 rows of ordinary record JSON at a 6,000-char cap::

    rendered 816 chars = 13.6% of the budget
    rows visible: 8 of 120   ("<elided 112 more items>")

86% of the budget unspent, on a shape that is everywhere -- any list endpoint,
any search result set, any `rows`/`items`/`results` envelope.

## Why doubling alone was not the fix

The first attempt only DOUBLED the ration while the render fit. It stopped at
52.9%: 32 rows rendered 3,173 characters and 64 overflowed 6,000, so it never
tried 48. An overflowing ration now becomes the upper bracket and the search
bisects into it -- BF-761's lesson, one dimension over.

## What must not regress

BF-728 rationed containers deliberately. PyPI's `/json` keys `releases` by
version string: ~1,500 entries of noise beside the few keys that are the
answer. The ration is right when the budget is tight, so this only ever moves
UP from BF-728's defaults, and only while the render both still fits and still
grows. The BF-728 suites are unmodified and green.
"""

from __future__ import annotations

import json

import pytest

import probos.cognitive.swe_harness.tool_call as tool_call
from probos.cognitive.swe_harness.tool_call import render_tool_output

CAP = 6000


def _rows(n: int = 120) -> dict:
    """The measured shape: a record array under a container key."""
    return {
        "rows": [
            {
                "id": i,
                "name": f"widget-{i:03d}",
                "status": "active" if i % 3 else "retired",
                "owner": f"team-{i % 7}",
                "updated": f"2026-0{(i % 9) + 1}-1{i % 10}",
            }
            for i in range(n)
        ]
    }


def _pypi() -> dict:
    """Identity keys first, a huge dict of noise last. The BF-728 case."""
    return {
        "info": {"name": "probos", "version": "1.4.2", "summary": "x" * 200},
        "releases": {
            f"1.{a}.{b}": [{"filename": f"probos-1.{a}.{b}.whl", "size": 12345}]
            for a in range(30)
            for b in range(50)
        },
    }


def _renders(value, *, max_chars: int) -> tuple[str, int]:
    """Render, counting TOP-LEVEL renders (``_shrink`` at depth 0)."""
    count = 0
    real = tool_call._shrink

    def counting(*args, **kwargs):
        nonlocal count
        if kwargs.get("depth") == 0:
            count += 1
        return real(*args, **kwargs)

    tool_call._shrink = counting
    try:
        return render_tool_output(value, max_chars=max_chars), count
    finally:
        tool_call._shrink = real


# ── the acceptance criteria ───────────────────────────────────────


def test_a_120_row_array_spends_most_of_the_budget() -> None:
    """The headline criterion: >80% of a 6,000-char cap. Was 13.6%."""
    rendered = render_tool_output(_rows(), max_chars=CAP)

    assert len(rendered) <= CAP
    assert len(rendered) > CAP * 0.8, (
        f"{len(rendered)} of {CAP} = {100 * len(rendered) / CAP:.1f}%"
    )


def test_far_more_rows_survive_than_the_default_ration() -> None:
    """The budget can be spent on one fat row instead of many, so the row
    count is asserted rather than only the character count."""
    rendered = render_tool_output(_rows(), max_chars=CAP)
    visible = sum(1 for i in range(120) if f"widget-{i:03d}" in rendered)

    assert visible > tool_call._LIST_KEEP * 4, visible


def test_pypi_still_surfaces_the_version_and_still_collapses_releases() -> None:
    """The case the rations exist for. BF-728's own suites are unmodified and
    green; this states the property here too, because it is the thing this
    change could most plausibly break."""
    rendered = render_tool_output(_pypi(), max_chars=CAP)

    assert len(rendered) <= CAP
    assert "1.4.2" in rendered, "the answer must survive"
    assert "<elided" in rendered, "and the noise must still be collapsed"


def test_retention_is_monotone_in_the_cap() -> None:
    """A bigger budget must never return less -- checked at ADJACENT caps.

    A sparse sweep (500, 1000, 2000, ...) cannot see this. The first version of
    the ration search interpolated the first jump from ``max_chars`` directly,
    so one extra character moved the whole ladder: review measured 5,954 -> 126
    rows and 5,955 -> 120 rows, six rows lost by RAISING the budget. Across
    caps 3,000-12,000 on three shapes that version dipped at 20 adjacent caps,
    worst 612 characters. The ladder is quantised to powers of two so every cap
    explores the same rations.
    """
    shapes = {
        "tokens": {
            "rows": [
                {"id": i, "token": f"TOKEN-{i:03d}", "note": ""} for i in range(300)
            ]
        },
        "records": _rows(),
        "flat": {"rows": list(range(5_000))},
    }
    for name, value in shapes.items():
        previous = -1
        for cap in range(4_000, 4_600):
            length = len(render_tool_output(value, max_chars=cap))
            assert length >= previous, (
                f"{name}: raising the cap to {cap} returned {length} "
                f"characters, down from {previous}"
            )
            previous = length


def test_every_render_stays_within_its_cap() -> None:
    """For every cap that can carry the shape at all.

    ``render_tool_output`` does not promise to fit an arbitrarily small cap --
    its docstring says the character-level AD-1148 bound downstream is the
    backstop, and at a cap below one record the elision markers themselves are
    the overflow. Verified against HEAD: ``rows`` at a 120-char cap renders 232
    characters both before and after this change, byte for byte.
    """
    for cap in (300, 700, 1500, 3000, 6000, 20000):
        rendered = render_tool_output(_rows(), max_chars=cap)
        assert len(rendered) <= cap, (cap, len(rendered))


def test_a_cap_too_small_for_one_record_is_unchanged_PRE_EXISTING() -> None:
    """Named so it is not read as something BF-762 introduced.

    Measured identical at HEAD and here: 232 characters at a 120-char cap. The
    guarantee that DOES hold is that a render is never longer than the value it
    came from, so the downstream bound has something smaller to work on.
    """
    value = _rows()
    rendered = render_tool_output(value, max_chars=120)

    assert len(rendered) > 120, "pre-existing: the markers are the overflow"
    assert len(rendered) < len(str(value)), "but it never grows the value"


def test_the_ladder_is_the_same_at_every_cap() -> None:
    """The property that MAKES it monotone, asserted directly.

    Quantising to powers of two is not cosmetic: it is what stops the candidate
    ration set moving with the budget. Two caps a single character apart must
    reach the same or a further rung, never a different one.
    """
    value = {
        "rows": [{"id": i, "token": f"TOKEN-{i:03d}", "note": ""} for i in range(300)]
    }
    for cap in (5_954, 7_331, 9_791):
        here = len(render_tool_output(value, max_chars=cap))
        there = len(render_tool_output(value, max_chars=cap + 1))
        assert there >= here, (cap, here, there)


def test_a_very_large_array_also_spends_its_budget() -> None:
    """The fix must scale, not fit the one fixture it was measured on.

    Doubling from eight reaches 20,000 rows only after eleven rounds, so within
    the probe budget it delivered 6,475 of a 60,000-char cap -- 10.8%, the same
    starvation one order of magnitude up. The first jump is interpolated from
    the budget instead, which reaches it in one probe.
    """
    huge = {"rows": [{"id": i, "n": f"w{i}"} for i in range(20_000)]}
    rendered = render_tool_output(huge, max_chars=60_000)

    assert len(rendered) <= 60_000
    assert len(rendered) > 60_000 * 0.8, len(rendered)


def test_an_over_estimated_jump_is_bracketed_back() -> None:
    """The estimate is linear and the render is not, so it can overshoot. That
    must cost one probe and become the upper bracket, not the whole budget."""
    for cap in (700, 2000, 9000):
        rendered, count = _renders(_rows(400), max_chars=cap)
        assert len(rendered) <= cap, (cap, len(rendered))
        assert count <= 3 + tool_call._ALLOWANCE_PROBES + tool_call._RATION_PROBES


def test_the_probe_budget_is_what_stops_the_search() -> None:
    """The bound is a deliberate cost/benefit trade and must be observable.

    Measured on a 20,000-row array at a 60,000 cap: bounded renders 7 times,
    unbounded 15 and delivers ~6% more. If this stops distinguishing them the
    bound has become decorative.
    """
    huge = {"rows": [{"id": i, "n": f"w{i}"} for i in range(20_000)]}
    _, count = _renders(huge, max_chars=60_000)
    assert count <= 3 + tool_call._ALLOWANCE_PROBES + tool_call._RATION_PROBES
    assert count <= 10, count


def test_the_render_count_stays_a_fixed_bound() -> None:
    """AD-1151 R3: a serialise-per-elision shrink loop measured 33s for 2,000
    entries inside an async method. This must never become that shape.

    The empirical ceiling is asserted as well as the arithmetic one: an
    unbounded ration loop still terminates on these fixtures, so only a tight
    number separates it from the bounded one (measured 11 bounded, 16
    unbounded).
    """
    _, count = _renders(_rows(), max_chars=CAP)
    ceiling = 3 + tool_call._ALLOWANCE_PROBES + tool_call._RATION_PROBES
    assert count <= ceiling, (count, ceiling)
    assert count <= 13, count


# ── the search's own shape ────────────────────────────────────────


def test_doubling_alone_would_not_have_reached_the_target() -> None:
    """Pins WHY the search brackets rather than only doubling.

    Measured: 32 rows rendered 3,173 characters and 64 overflowed 6,000, so a
    doubling-only search stopped at 52.9%, never trying 48. If this ever
    passes with `_RATION_PROBES` worth of pure doubling, the bisection has been
    removed and the array is starved again.
    """
    from probos.cognitive.swe_harness.tool_call import _shrink

    value = _rows()
    doubled_only = None
    keeps = (tool_call._LIST_KEEP, tool_call._DICT_KEEP)
    for _ in range(tool_call._RATION_PROBES):
        wider = (keeps[0] * 2, keeps[1] * 2)
        candidate = str(
            _shrink(value, value_max=CAP, list_keep=wider[0], dict_keep=wider[1], depth=0)
        )
        if len(candidate) > CAP:
            break
        keeps, doubled_only = wider, candidate

    assert doubled_only is not None
    assert len(doubled_only) <= CAP * 0.8, (
        "premise: pure doubling lands under the target, so reaching it proves "
        "the bracket search is doing the work"
    )
    assert len(render_tool_output(value, max_chars=CAP)) > len(doubled_only)


def test_a_ration_that_buys_nothing_is_not_taken() -> None:
    """A payload whose size is set by its LEAVES, not its breadth. Widening the
    ration cannot help, and spending probes on it would be waste -- and for a
    deep dict, would widen every level through ``max(1, dict_keep >> depth)``
    for no gain.

    The ceiling is tight on purpose: removing the still-grows guard leaves this
    payload at 12 renders against 3, and a loose ceiling let that through.
    """
    value = {"body": "z" * 50_000}
    rendered, count = _renders(value, max_chars=CAP)

    assert len(rendered) <= CAP
    assert count <= 6, count


def test_a_deep_dict_is_not_widened_superlinearly(monkeypatch) -> None:
    """``ration = max(1, dict_keep >> depth)`` means a raised ``dict_keep``
    widens deep levels superlinearly, which is why the decay exists.

    Asserted as an EQUALITY against the search disabled, rather than as a fit:
    this payload already overflows its smaller caps before BF-762 (measured
    identical at HEAD -- 1,826 characters at both a 500 and a 2,000 cap), so a
    fit assertion would fail for a reason that has nothing to do with this
    change. What matters is that the ration search declines to widen it at all,
    which is what the still-fits-and-still-grows condition buys.
    """
    deep = {
        f"k{i}": {f"j{j}": {f"m{m}": "x" * 40 for m in range(20)} for j in range(20)}
        for i in range(20)
    }
    for cap in (500, 2000, 6000):
        with_search = render_tool_output(deep, max_chars=cap)
        monkeypatch.setattr(tool_call, "_RATION_PROBES", 0)
        without_search = render_tool_output(deep, max_chars=cap)
        monkeypatch.undo()
        assert with_search == without_search, cap


def test_a_small_payload_is_returned_untouched() -> None:
    """Below the cap nothing is searched at all -- the pre-BF-728 identity."""
    value = {"answer": "fifteen", "rows": [1, 2, 3]}
    assert render_tool_output(value, max_chars=CAP) == str(value)


def test_the_cap_off_switch_still_returns_the_plain_rendering() -> None:
    value = _rows()
    assert render_tool_output(value, max_chars=0) == str(value)


def test_a_json_text_leaf_still_benefits() -> None:
    """An embedded JSON document (http_fetch's ``body``) is recursed into, so
    the ration search reaches it through the leaf rather than only the top."""
    doc = json.dumps([{"id": i, "name": f"row {i}"} for i in range(200)], indent=2)
    rendered = render_tool_output({"body": doc, "status": 200}, max_chars=CAP)

    assert len(rendered) <= CAP
    assert len(rendered) > CAP * 0.5, len(rendered)


@pytest.mark.parametrize("rows", [9, 17, 33, 65, 400])
def test_the_search_lands_somewhere_useful_at_every_size(rows: int) -> None:
    """Not just the one fixture the defect was measured on."""
    rendered = render_tool_output(_rows(rows), max_chars=CAP)
    assert len(rendered) <= CAP
    if len(str(_rows(rows))) > CAP:
        assert len(rendered) > CAP * 0.5, (rows, len(rendered))
    else:
        assert rendered == str(_rows(rows))
