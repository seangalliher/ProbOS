"""AD-1250 (#1294): the renderer spends a tight budget on per-record detail, not on breadth.

``render_tool_output`` searches two dimensions in a fixed order: the per-leaf
ALLOWANCE first (BF-761), then the container RATION (BF-762) at the allowance the
first search settled on. BF-762's review measured that a JOINT search -- lowering
the allowance before calling a wider ration an overflow -- "retained 32 rows
instead of 13 in one cap-3,000 mixed payload". AD-1250 reproduced it: 120
records of a 10-character name and a 168-character prose description at a 3,000
cap. The ordered search keeps 13 records with every description WHOLE (2,809
characters, 93.6% of the cap, 2,314 characters of content, 7 renders). A
fits-gated joint search keeps 32 records at allowance 0, where every description
is replaced by its elision marker (2,490 characters, 83.0%, 320 characters of
content -- the names alone); the literal reading keeps 16, every description cut.

Measured across 36 payload shapes at ten caps from 1,000 to 50,000: wherever a
breadth-leaning variant kept more records than the ordered search, it kept less
leaf content in all but one to three of those combinations (99 of 100 for the
fits-gated search). On a PyPI payload with a prose README, the three variants
that accept a narrower allowance whenever it fits spent the budget on the
release list BF-728 calls noise. So the ordered search is the decision, not an
accident, and these tests pin it. See DECISIONS.md AD-1250 for the options
measured and why they were declined.
"""

from __future__ import annotations

import re

import pytest

import probos.cognitive.swe_harness.tool_call as tool_call
from probos.cognitive.swe_harness.tool_call import (
    ToolCallResult,
    _shrink,
    render_tool_output,
)
from probos.tools.protocol import ToolResult
from tests.test_bf728_structured_tool_output import _as_http_fetch_output

CAP = 3_000
_WORDS = (
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
)


def _prose(n: int, seed: int) -> str:
    """Readable text of EXACTLY ``n`` characters: whitespace-bearing, so
    ``_looks_like_text`` treats it as prose, and 1.00x repr expansion."""
    out: list[str] = []
    i = seed
    while sum(len(w) + 1 for w in out) < n + 16:
        out.append(_WORDS[i % len(_WORDS)])
        i += 7
    text = " ".join(out)[:n]
    assert len(text) == n
    return text


def _records(n: int = 120, desc: int = 168) -> dict:
    """The #1294 shape: short identifying leaves and one long prose leaf."""
    return {
        "rows": [
            {"id": i, "name": f"widget-{i:03d}", "desc": _prose(desc, i)}
            for i in range(n)
        ]
    }


def _varied(n: int = 120) -> dict:
    """The same records with the long leaf varying 40-439 characters."""
    return {
        "rows": [
            {"id": i, "name": f"widget-{i:03d}", "desc": _prose(40 + (i * 37) % 400, i)}
            for i in range(n)
        ]
    }


def _visible(rendered: str, n: int) -> list[int]:
    return [i for i in range(n) if f"'name': 'widget-{i:03d}'" in rendered]


def _assert_every_kept_record_is_whole(rendered: str, value: dict) -> list[int]:
    rows = value["rows"]
    kept = _visible(rendered, len(rows))
    assert kept == list(range(len(kept))), "the records kept must be the first ones"
    for i in kept:
        assert repr(rows[i]["desc"]) in rendered, f"record {i}'s description was cut"
    assert "more chars>" not in rendered, "no leaf may be truncated"
    return kept


def test_the_reproduced_payload_keeps_thirteen_whole_records() -> None:
    """The #1294 payload. 13 whole records, not 32 marker-only ones."""
    value = _records()
    rendered = render_tool_output(value, max_chars=CAP)

    assert CAP * 0.9 < len(rendered) <= CAP, len(rendered)
    kept = _assert_every_kept_record_is_whole(rendered, value)
    assert len(kept) == 13, kept
    assert "<elided 107 more items>" in rendered

    # And that is what the model receives: from_tool_result is the one
    # production caller that bounds a structured result.
    tcr = ToolCallResult.from_tool_result(
        "call-1", ToolResult(output=value), 1.0, max_chars=CAP
    )
    assert tcr.output == rendered


def test_the_breadth_trade_was_available_and_declined() -> None:
    """Computed, not remembered: the 32-record render exists, fits, and carries
    no description at all -- while 14 whole records do not fit. So 13 is the
    most whole records this cap holds, and the fits-gated joint search's 32
    are names.

    If this stops holding, the fixture no longer reproduces #1294 and the test
    above is no longer testing the decision.
    """
    value = _records()
    wide = str(_shrink(value, value_max=0, list_keep=32, dict_keep=160, depth=0))
    assert len(wide) <= CAP, len(wide)
    assert wide.count("<elided 168 more chars>") == 32, "every description elided"
    assert len(_visible(wide, 120)) == 32

    fourteen = str(_shrink(value, value_max=CAP, list_keep=14, dict_keep=70, depth=0))
    assert len(fourteen) > CAP, len(fourteen)
    assert "more chars>" not in fourteen, "premise: at the settled allowance every record is whole"


def test_a_shorter_leaf_array_keeps_every_record_whole() -> None:
    """A second point on the same shape: 100-character descriptions keep 20
    whole records (2,947 characters). Measured: the fits-gated and grow-gated
    joint searches keep 32 records here with every description elided."""
    value = _records(desc=100)
    rendered = render_tool_output(value, max_chars=CAP)

    assert len(rendered) <= CAP
    kept = _assert_every_kept_record_is_whole(rendered, value)
    assert len(kept) == 20, kept


def test_a_prose_readme_keeps_the_budget_over_the_release_list() -> None:
    """BF-728's own case with a README that is PROSE, as real ones are.

    BF-728's fixtures use an opaque ``"R" * 190_000`` description, which is
    elided whatever the allowance, so they cannot see this trade. At 6,000 the
    ordered search keeps 5,323 characters of README and 5 releases. The three
    variants that accept a narrower allowance whenever it fits kept 80 releases
    and 550-608 characters of README; the two that re-search only on overflow
    kept the README here.
    """
    readme = _prose(50_000, 3)
    payload = {
        "info": {
            "author": "Amazon Web Services",
            "description": readme,
            "summary": "The AWS SDK for Python",
            "version": "1.43.67",
        },
        "releases": {
            f"1.0.{i}": [{"filename": f"boto3-1.0.{i}.tar.gz", "size": 1234}]
            for i in range(1_500)
        },
    }
    rendered = render_tool_output(_as_http_fetch_output(payload), max_chars=6_000)

    assert len(rendered) <= 6_000
    assert "'version': '1.43.67'" in rendered, "the answer must survive"
    assert "<elided 1495 more keys>" in rendered, "the release list stays collapsed"
    cuts = re.findall(r"<elided (\d+) more chars>", rendered)
    assert len(cuts) == 1, cuts
    kept = len(readme) - int(cuts[0])
    assert kept > 6_000 * 0.8, f"only {kept} characters of README survived"


@pytest.mark.parametrize("make", [_records, _varied], ids=["desc168", "varied"])
def test_retention_is_monotone_in_the_cap_on_long_leaf_records(make) -> None:
    """BF-762's sweep, in the regime where the two search orders differ.

    BF-762's three sweep shapes carry only short leaves: measured, every
    variant renders them identically at ten caps from 1,000 to 50,000 and none
    dips over BF-762's own 4,000-4,599 sweep, so that sweep cannot tell the
    orders apart. Measured on these two shapes over caps 2,000-7,999: 0 dips
    for the ordered search, and 115-120 row dips for the literal joint search.
    Chars AND records are checked.
    """
    value = make()
    previous_len = previous_rows = -1
    lengths = []
    for cap in range(2_500, 3_500):
        rendered = render_tool_output(value, max_chars=cap)
        rows = len(_visible(rendered, 120))
        assert len(rendered) >= previous_len, (cap, previous_len, len(rendered))
        assert rows >= previous_rows, (cap, previous_rows, rows)
        previous_len, previous_rows = len(rendered), rows
        lengths.append(len(rendered))
    assert lengths[-1] > lengths[0], "the cap must be load-bearing across the sweep"


def test_the_reproduced_payload_costs_no_extra_renders(monkeypatch) -> None:
    """The decision keeps BF-762's render bound. Measured 7 depth-zero renders
    here; on this payload the joint variants took 11-22 and the breadth-first
    reorder 10."""
    count = 0
    real = tool_call._shrink

    def counting(*args, **kwargs):
        nonlocal count
        if kwargs.get("depth") == 0:
            count += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(tool_call, "_shrink", counting)
    render_tool_output(_records(), max_chars=CAP)
    assert count <= 3 + tool_call._ALLOWANCE_PROBES + tool_call._RATION_PROBES
    assert count <= 8, count
