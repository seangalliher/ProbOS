"""BF-759 (#1217): every MCP content tool delivered a skeleton, not content.

BF-728 taught :func:`render_tool_output` to keep a structure's SHAPE when the
value is too big for the budget, because for PyPI's ``/json`` the bulk is noise
and the keys are the answer. An MCP tool result is the opposite shape.

``{"content": [{"type": "text", "text": <whole document>}]}`` is the MCP
STANDARD content envelope, so the payload is one string leaf. A leaf over its
allowance was replaced wholesale by a marker — the shape survived intact and
the document did not.

Measured on the live vessel: ``microsoft_docs_fetch`` on a 13,027-character
page returned **81 characters** to the model::

    {'content': [{'type': 'text', 'text': '<elided 13027 chars>'}],
     'isError': False}

Zero percent of the document, and 1.4% of a 6,000-character budget spent. The
allowance is ``max_chars // 20`` = 300 at the live cap, which assumes about
twenty significant leaves; a document envelope has one. Nothing errored, so
nothing in the fault machinery (AD-1168/1169/1170) could see it — the agent
simply fell back to ``run_python`` against URLs it had already fetched.

Two properties are asserted here and each was arrived at by being wrong first:

* **An oversized leaf is truncated, not discarded.** No allowance can keep a
  13 KB document under a 6 KB cap whole, so the only way to deliver any of it
  is to cut it. Returning none of a payload while the budget goes unspent is
  never the right trade.
* **Leftover budget is spent.** The passes only ever tighten, so a single-leaf
  payload settles far under budget with that leaf gone. One further render
  raises the allowance by the remainder; ``_shrink`` is monotone in
  ``value_max`` so the result is a superset, and it is kept only if it fits.

The diagnosis was wrong the first time and that is worth recording: this was
first attributed to ``truncate_tool_output`` losing "53% from the middle". That
function never sees the document — ``render_tool_output`` runs first at the
``ToolCallResult.from_tool_result`` boundary and removes 100%, after which the
character-slicer receives 81 characters and is a no-op. Measuring the second
stage of a pipeline without checking that the first had already run is the same
half-chain error this repo keeps writing warnings about.
"""

from __future__ import annotations

import base64
import json
import re
import time

import pytest

from probos.cognitive.swe_harness.tool_call import (
    _ELIDED_SPAN,
    ToolCallResult,
    _shrink,
    _truncate_leaf,
    render_tool_output,
)
from probos.tools.protocol import ToolResult

# The live cap on the Captain's vessel (``agentic_loop.tool_result_max_chars``).
LIVE_CAP = 6000


def _mcp_envelope(text: str) -> dict:
    """The MCP standard ``tools/call`` result, exactly as ``MCPClient`` returns it.

    ``_McpTool.invoke`` hands this dict straight to ``ToolResult(output=...)``,
    so this is the real value ``render_tool_output`` receives.
    """
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _a_page(chars: int) -> str:
    """Prose, not filler — a repeated marker would let a broken slice look fine."""
    unit = "Section {}: transports, lifecycle and capabilities. "
    body = "".join(unit.format(i) for i in range(chars))
    assert len(body) >= chars, "fixture must produce the length it is asked for"
    return body[:chars]


def _kept_document_chars(rendered: str, document: str) -> int:
    """Length of the longest leading run of ``document`` present in ``rendered``.

    Binary search rather than a scan: the page is prose with repeated phrasing,
    so a per-character membership test would report matches that are not a
    contiguous prefix.
    """
    low, high = 0, len(document)
    while low < high:
        mid = (low + high + 1) // 2
        if document[:mid] in rendered:
            low = mid
        else:
            high = mid - 1
    return low


def _kept_document_tail_chars(rendered: str, document: str) -> int:
    """Length of the longest trailing run of ``document`` present in ``rendered``."""
    low, high = 0, len(document)
    while low < high:
        mid = (low + high + 1) // 2
        if document[len(document) - mid :] in rendered:
            low = mid
        else:
            high = mid - 1
    return low


# ── (1) the headline ───────────────────────────────────────────────────────
class TestTheDocumentSurvives:
    def test_an_mcp_page_is_no_longer_returned_as_a_skeleton(self) -> None:
        """Fails before the fix: the whole page rendered as one elision marker."""
        page = _a_page(13_027)
        rendered = render_tool_output(_mcp_envelope(page), max_chars=LIVE_CAP)

        assert page[:2_000] in rendered, "the document itself must reach the model"
        assert "<elided 13027 chars>" not in rendered

    def test_the_old_path_really_did_deliver_nothing(self) -> None:
        """The counterfactual, so this suite proves the fix is load-bearing.

        The 81-character rendering measured on the live vessel is what the
        pre-BF-759 allowance produces: ``max_chars // 20`` = 300 at the live
        cap, against a leaf of 13,027.
        """
        page = _a_page(13_027)
        assert LIVE_CAP // 20 == 300
        assert len(page) > 300, "the leaf must exceed the old allowance"
        old_rendering = str(_mcp_envelope(f"<elided {len(page)} chars>"))
        assert len(old_rendering) == 81
        assert _kept_document_chars(old_rendering, page) == 0

    def test_the_budget_is_actually_spent(self) -> None:
        """1.4% of the budget used was the real signal; a bound is not a target
        to stay under."""
        rendered = render_tool_output(_mcp_envelope(_a_page(13_027)), max_chars=LIVE_CAP)
        assert len(rendered) <= LIVE_CAP
        assert len(rendered) > LIVE_CAP * 0.9

    def test_the_elision_is_still_counted_and_reconciles(self) -> None:
        page = _a_page(13_027)
        rendered = render_tool_output(_mcp_envelope(page), max_chars=LIVE_CAP)
        reported = int(re.search(r"<elided (\d+) more chars>", rendered).group(1))
        assert 0 < reported < len(page)
        head = _kept_document_chars(rendered, page)
        tail = _kept_document_tail_chars(rendered, page)
        assert head + reported + tail == len(page), (
            "head + reported + tail must equal what the tool returned"
        )

    def test_the_model_receives_it_through_the_real_consumer(self) -> None:
        """``ToolCallResult.from_tool_result`` is the boundary the loop uses;
        assert at the consumer, not at the helper."""
        page = _a_page(13_027)
        tcr = ToolCallResult.from_tool_result(
            "call-1", ToolResult(output=_mcp_envelope(page)), 1.0, max_chars=LIVE_CAP
        )
        assert not tcr.is_error
        assert len(tcr.output) > LIVE_CAP * 0.9
        assert page[:2_000] in tcr.output


# ── (2) the whole class, not one server ────────────────────────────────────
class TestEveryMcpContentToolNotJustLearn:
    @pytest.mark.parametrize(
        "envelope",
        [
            {"content": [{"type": "text", "text": _a_page(40_000)}]},
            {"content": [{"type": "text", "text": _a_page(40_000)}], "isError": False},
            {
                "content": [{"type": "text", "text": _a_page(40_000)}],
                "structuredContent": {"ok": True},
                "isError": False,
            },
        ],
        ids=["bare", "with-iserror", "with-structured-content"],
    )
    def test_the_standard_envelope_delivers_content_in_every_variant(
        self, envelope: dict
    ) -> None:
        rendered = render_tool_output(envelope, max_chars=LIVE_CAP)
        assert _kept_document_chars(rendered, _a_page(40_000)) > 3_000

    def test_several_content_blocks_are_all_represented(self) -> None:
        """Both blocks carry their OWN marker. Review caught the first version
        of this passing with block one deleted, because the shared prose let
        block two satisfy every assertion."""
        envelope = {
            "content": [
                {"type": "text", "text": "FIRST-BLOCK-MARKER " + _a_page(9_000)},
                {"type": "text", "text": "SECOND-BLOCK-MARKER " + _a_page(9_000)},
            ]
        }
        rendered = render_tool_output(envelope, max_chars=LIVE_CAP)
        assert "FIRST-BLOCK-MARKER" in rendered
        assert "SECOND-BLOCK-MARKER" in rendered
        assert len(rendered) <= LIVE_CAP


# ── (3) the growth render is monotone, bounded and declined when it misses ──
class TestGrowthIsSafe:
    def test_a_larger_cap_never_returns_less(self) -> None:
        """Monotone in the cap. AD-1151 R2's inert-second-consumer defect was a
        cap that changed nothing; assert across several caps, never one."""
        envelope = _mcp_envelope(_a_page(40_000))
        lengths = [
            len(render_tool_output(envelope, max_chars=cap))
            for cap in (500, 1_000, 2_000, 6_000, 12_000, 30_000)
        ]
        assert lengths == sorted(lengths)
        assert lengths[0] < lengths[-1], "the cap must be load-bearing"

    def test_every_render_still_respects_the_cap(self) -> None:
        envelope = _mcp_envelope(_a_page(40_000))
        for cap in (200, 500, 1_000, 2_000, 6_000, 12_000):
            assert len(render_tool_output(envelope, max_chars=cap)) <= cap

    def test_a_structure_with_many_oversized_leaves_still_fits(self) -> None:
        """Growth raises the allowance for EVERY leaf, so a multi-leaf payload
        overshoots and the grown render must be declined rather than returned."""
        many = {f"field_{i}": _a_page(5_000) for i in range(40)}
        rendered = render_tool_output(many, max_chars=LIVE_CAP)
        assert len(rendered) <= LIVE_CAP
        assert "field_0" in rendered

    @pytest.mark.parametrize("value_max", [48, 120, 300, 2_000])
    def test_truncation_never_makes_a_value_longer_than_it_was(
        self, value_max: int
    ) -> None:
        """Asserted on ``_truncate_leaf``, which is where the rule lives.

        The first version of this drove the rule through ``render_tool_output``
        at a chosen cap. Review mutation-checked it by deleting the guard: it
        still passed, because the outer pass sequence simply tightened again and
        hid the inflated leaf. The band that matters is narrow — a value between
        the allowance and the allowance plus the marker — so it has to be walked
        deliberately rather than hoped for.
        """
        marker_size = len(_ELIDED_SPAN.format(n=10_000))
        for length in range(value_max + 1, value_max + marker_size + 20):
            value = ("word " * length)[:length]
            out = _truncate_leaf(value, value_max)
            assert len(out) <= len(value), (
                f"a {len(value)}-char leaf rendered as {len(out)} chars "
                f"at allowance {value_max}"
            )

    def test_a_growth_that_would_shrink_the_render_is_declined(self) -> None:
        """``_shrink`` is not monotone at the JSON-recursion boundary.

        A JSON-looking string is walked only while it EXCEEDS the allowance, so
        raising the allowance past its length returns it verbatim instead — a
        different shape, and here a smaller one. This fixture is the live repro:
        at cap 300 the fitted render is 210 characters and the grown one 181.
        Without the comparison in ``render_tool_output`` the shorter render
        would be returned, and the docstring's monotonicity claim would be the
        kind of comment that says what the code does not do.
        """
        nested = json.dumps({f"k{i}": i for i in range(16)}, separators=(",", ":"))
        assert len(nested) == 125, "the flip needs the inner string near the allowance"
        value = {
            "body": json.dumps(
                {"nested": nested, "bulk": "B" * 10_000}, separators=(",", ":")
            )
        }
        fitted = str(
            _shrink(value, value_max=120, list_keep=8, dict_keep=40, depth=0)
        )
        grown = str(
            _shrink(value, value_max=210, list_keep=8, dict_keep=40, depth=0)
        )
        assert len(grown) < len(fitted), (
            "fixture no longer reproduces the flip; find a new one before "
            "relaxing the guard"
        )
        assert len(render_tool_output(value, max_chars=300)) == len(fitted)

    def test_cost_stays_bounded_with_the_extra_render(self) -> None:
        """AD-1151 R3 measured a serialise-per-elision shrink loop at 33 s. The
        growth render adds one pass, not a search."""
        big = {f"k{i}": {"vals": list(range(50)), "note": "N" * 5_000} for i in range(2_000)}
        start = time.perf_counter()
        rendered = render_tool_output(big, max_chars=LIVE_CAP)
        elapsed = time.perf_counter() - start
        assert isinstance(rendered, str)
        assert elapsed < 5.0, f"took {elapsed:.1f}s — this has become a shrink loop"


# ── (4) what must NOT be truncated: opaque leaves, and a tool's own marker ──
class TestTheCarveOuts:
    """Both were found by adversarial review, not by reasoning about the fix."""

    def _base64_blob(self, raw_bytes: int) -> str:
        return base64.b64encode(bytes(range(256)) * (raw_bytes // 256)).decode()

    def test_an_mcp_image_block_keeps_its_counted_elision(self) -> None:
        """MCP defines ``image`` and ``audio`` blocks whose ``data`` is base64.
        Half a base64 blob is not half an answer — truncating it would spend
        the whole budget on characters the model can do nothing with."""
        blob = self._base64_blob(20_000)
        envelope = {
            "content": [{"type": "image", "data": blob, "mimeType": "image/png"}],
            "isError": False,
        }
        rendered = render_tool_output(envelope, max_chars=LIVE_CAP)
        assert f"<elided {len(blob)} chars>" in rendered
        assert len(rendered) < 200, "a base64 blob must not spend the budget"

    def test_a_text_block_of_the_same_size_is_delivered(self) -> None:
        """The counterfactual: the carve-out keys on the CONTENT, not on the
        size, so an equally large document is unaffected."""
        page = _a_page(20_000)
        rendered = render_tool_output(_mcp_envelope(page), max_chars=LIVE_CAP)
        assert len(rendered) > LIVE_CAP * 0.9

    def test_a_tools_own_trailing_marker_survives_the_cut(self) -> None:
        """AD-1153 closes a bounded page read by telling the agent how to get
        the rest. A head-only cut removed exactly that sentence."""
        recovery = (
            "\n\n... [truncated: 90000 characters elided from this page read. "
            "Re-run extract_text with a narrower selector to retrieve the "
            "elided region.] ...\n\n"
        )
        out = {"action": "extract_text", "text": _a_page(8_000) + recovery}
        rendered = render_tool_output(out, max_chars=LIVE_CAP)
        assert "narrower selector" in rendered, (
            "the recovery advice is the one part the agent cannot reconstruct"
        )

    def test_the_head_is_kept_too_not_only_the_tail(self) -> None:
        page = _a_page(13_027)
        rendered = render_tool_output(_mcp_envelope(page), max_chars=LIVE_CAP)
        assert _kept_document_chars(rendered, page) > 2_000
        assert _kept_document_tail_chars(rendered, page) > 500


# ── (5) BF-728's own guarantees are unmoved ────────────────────────────────
class TestBf728StillHolds:
    def _pypi(self) -> dict:
        payload = {
            "info": {
                "description": "R" * 190_000,
                "summary": "The AWS SDK for Python",
                "version": "1.43.67",
            },
            "releases": {
                f"1.0.{i}": [{"filename": f"boto3-1.0.{i}.tar.gz"}] for i in range(1_500)
            },
        }
        body = json.dumps(payload)
        return {"url": "https://pypi.org/pypi/boto3/json", "status_code": 200, "body": body}

    def test_the_wanted_scalar_still_survives(self) -> None:
        rendered = render_tool_output(self._pypi(), max_chars=LIVE_CAP)
        assert "'version': '1.43.67'" in rendered
        assert len(rendered) <= LIVE_CAP

    def test_an_embedded_json_body_is_still_recursed_not_cut(self) -> None:
        out = {"body": json.dumps({"deep": {"needle": "FOUND"}, "bulk": "B" * 500_000})}
        assert "FOUND" in render_tool_output(out, max_chars=LIVE_CAP)

    def test_unbounded_is_still_byte_identical_to_str(self) -> None:
        out = self._pypi()
        assert render_tool_output(out, max_chars=0) == str(out)

    def test_a_result_that_already_fits_is_still_byte_identical(self) -> None:
        out = _mcp_envelope("short answer")
        assert render_tool_output(out, max_chars=LIVE_CAP) == str(out)

    def test_a_string_output_is_still_never_restructured(self) -> None:
        tcr = ToolCallResult.from_tool_result(
            "call-1", ToolResult(output="A" * 50_000), 1.0, max_chars=100
        )
        assert tcr.output == "A" * 50_000
