"""BF-761 (#1219): BF-759's growth render was defeated by escape expansion.

BF-759 made an oversized tool result carry content instead of a skeleton, then
spend the leftover budget in one further render at ``value_max + headroom``.
Measured on the running vessel at a 6,000-character cap, it was delivering
**3% of the budget**:

===================================  ==========  =========  =======
tool                                 payload     delivered  % of doc
===================================  ==========  =========  =======
``microsoft_docs_fetch`` (Functions)   10,447         390     3.0%
``microsoft_docs_fetch`` (SRE Agent)   13,775         388     2.8%
``microsoft_docs_fetch`` (Container)    8,515         379     4.4%
``run_python`` reading ``README.md``  ~23,700        ~460     1.9%
===================================  ==========  =========  =======

390 is the pass-1 render at ``max_chars // 20`` = 300. The growth render ran
and was DECLINED every time, so the result fell back to one twentieth of the
budget — the exact ratio BF-759 existed to remove.

Cause: ``_shrink`` measures a string leaf in RAW characters while the budget is
checked against the repr, where ``\\r``, ``\\n``, quotes and backslashes each
expand. Documentation is CRLF markdown at about 1.10x, so a raw slice sized to
the budget renders past it, one optimistic attempt overshoots, and there is no
second try.

**Why BF-759's own tests passed.** Its ``_a_page`` fixture generates prose
joined by spaces — 1.00x expansion, the single payload class where a raw-space
guess happens to land. Every "the budget is spent" assertion held on a payload
that does not occur in production. That is the fixture analogue of a test double
being more capable than the real object, and it is why this suite asserts
retention as a fraction of the CAP across several expansion ratios rather than
on one string.

The consequence was visible in the transcript, not just the numbers: the agent
called ``run_python`` seven times in one turn trying to read a README, because
each attempt returned ~460 characters and nothing told her the truncation was
the harness rather than her code.
"""

from __future__ import annotations

import json
import time

import pytest

from probos.cognitive.swe_harness.tool_call import (
    ToolCallResult,
    _shrink,
    render_tool_output,
)
from probos.tools.protocol import ToolResult

LIVE_CAP = 6000
RAW = 10_371


def _repeat_to(block: str, n: int) -> str:
    """Enough whole blocks to cover ``n``, then cut. A fixture that silently
    returns less than it was asked for is how BF-759's suite went blind."""
    body = block * (-(-n // len(block)))
    assert len(body) >= n
    return body[:n]


def _prose(n: int) -> str:
    """1.00x expansion. This is BF-759's fixture, kept as the control arm."""
    return _repeat_to("The Model Context Protocol is a client-server protocol. ", n)


def _crlf_markdown(n: int) -> str:
    """~1.10x. What learn.microsoft.com actually returns."""
    block = (
        "# Model Context Protocol bindings for Azure Functions overview\r\n"
        "\r\n"
        "The [Model Context Protocol (MCP)](https://github.com/mcp) is a\r\n"
        "client-server protocol designed for tool invocation.\r\n"
        "\r\n"
        "```json\r\n"
        '{\r\n    "mcp": {\r\n        "servers": {\r\n            "remote": {}\r\n'
        "        }\r\n    }\r\n}\r\n"
        "```\r\n"
        "\r\n"
    )
    return _repeat_to(block, n)


def _source_code(n: int) -> str:
    """~1.07x. What run_python returns when it reads a file."""
    block = (
        "def handle(request):\n"
        "    \"\"\"Dispatch one request.\"\"\"\n"
        "    if not request.ok:\n"
        "        raise ValueError('bad request')\n"
        "    return {'status': 200, 'body': request.body}\n"
        "\n"
    )
    return _repeat_to(block, n)


def _indented_json(n: int) -> str:
    """~1.15x. Tabs, newlines and escaped quotes together.

    Sized by ROW COUNT and returned whole. Review caught the first version
    slicing ``json.dumps(...)[:n]``, which cuts mid-string: the document did not
    parse, so ``_shrink`` took the not-JSON fallback and the case never
    exercised the recursion path it was named for.
    """
    rows = max(1, n // 60)
    body = json.dumps(
        {"rows": [{"name": f"row {i}", "note": "a\tb\nc\\d 'e'"} for i in range(rows)]},
        indent=2,
    )
    json.loads(body)
    return body


def _pure_newlines(n: int) -> str:
    """~1.50x. The worst ordinary escape density."""
    return _repeat_to("a\n", n)


def _backslash_heavy(n: int) -> str:
    """~1.16x. Windows paths and quoted strings, which is what a log looks like."""
    return _repeat_to("path\\to\\thing \"quoted\" 'single'\n", n)


def _tabs_and_newlines(n: int) -> str:
    """~1.67x. Indented output with almost nothing but whitespace."""
    return _repeat_to("\t\n\t\n a \t\n", n)


PAYLOADS = [
    pytest.param(_prose, 1.00, id="prose-1.00x"),
    pytest.param(_crlf_markdown, 1.10, id="crlf-markdown-1.10x"),
    pytest.param(_source_code, 1.07, id="source-code-1.07x"),
    pytest.param(_backslash_heavy, 1.16, id="backslash-heavy-1.16x"),
    pytest.param(_pure_newlines, 1.50, id="pure-newlines-1.50x"),
    pytest.param(_tabs_and_newlines, 1.67, id="tabs-newlines-1.67x"),
]


def _envelope(text: str) -> dict:
    """The MCP standard content envelope — one leaf holding the payload."""
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _reported_elision(rendered: str) -> int:
    marker = "<elided "
    if marker not in rendered or " more chars>" not in rendered:
        return 0
    return int(rendered.split(marker)[1].split(" more chars>")[0])


# ── (1) the headline: the budget is spent whatever the payload escapes to ──
class TestTheBudgetIsSpentOnRealContent:
    @pytest.mark.parametrize("make,expansion", PAYLOADS)
    def test_a_newline_dense_payload_fills_the_budget(self, make, expansion) -> None:
        """Fails before the fix on every case except the 1.00x control."""
        page = make(RAW)
        rendered = render_tool_output(_envelope(page), max_chars=LIVE_CAP)

        assert len(rendered) <= LIVE_CAP
        assert len(rendered) > LIVE_CAP * 0.95, (
            f"only {100 * len(rendered) / LIVE_CAP:.1f}% of the budget spent on a "
            f"{expansion}x payload; the allowance search stalled"
        )

    def test_a_many_leaf_payload_also_fills_the_budget(self) -> None:
        """The allowance a single-leaf document needs is enormous and the one a
        62-field dict needs is tiny. Review found the first version jumping
        straight to whole-leaf elision here and returning 2,232 characters with
        no payload at all, because it had only ever tried an allowance of 48.
        """
        many = {
            f"field_{i}": _prose(5_000) for i in range(62)
        }
        rendered = render_tool_output(many, max_chars=LIVE_CAP)
        assert len(rendered) <= LIVE_CAP
        assert len(rendered) > LIVE_CAP * 0.95
        assert all(f"field_{i}" in rendered for i in range(62)), "every key survives"
        assert rendered.count("The Model Context Protocol") >= 60, (
            "and every field carries content, not just a marker"
        )

    @pytest.mark.parametrize("make,expansion", PAYLOADS)
    def test_the_fixture_really_does_expand_as_claimed(self, make, expansion) -> None:
        """Guards the guard: if a fixture stops escaping, the case above stops
        testing anything and would pass for the wrong reason."""
        page = make(RAW)
        measured = len(repr(page)) / len(page)
        assert measured == pytest.approx(expansion, abs=0.03), (
            f"fixture expansion drifted to {measured:.2f}x"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="BF-762 (#1220): the container ration, not the allowance, bounds this",
    )
    def test_a_json_array_delivers_the_budget(self) -> None:
        """BF-762 (#1220): NOT YET TRUE, and expressed as the contract it should
        be rather than as the shape it currently has.

        A valid indented JSON array spends only ~7% of the budget. The allowance
        search is not what limits it — ``_LIST_KEEP`` rations the array to eight
        entries, so raising the allowance changes nothing and the search
        correctly saturates. That is the other dimension, and BF-761 does not
        touch it.

        ``strict=True`` so this flips to a failure the moment BF-762 lands,
        which is the point: a green test that requires the defect would make the
        fix look like a regression.
        """
        doc = _indented_json(7_500)
        rendered = render_tool_output(_envelope(doc), max_chars=LIVE_CAP)
        assert len(rendered) > LIVE_CAP * 0.8

    def test_a_json_array_is_currently_bounded_by_the_ration(self) -> None:
        """The shape as it actually ships, so the gap is visible and counted."""
        doc = _indented_json(7_500)
        rendered = render_tool_output(_envelope(doc), max_chars=LIVE_CAP)

        assert "more items" in rendered, "the ration must be counted"
        assert "'name': 'row 0'" in rendered, "and the shape must stay legible"
        assert len(rendered) <= LIVE_CAP

    def test_the_old_single_attempt_really_did_fall_back(self) -> None:
        """The counterfactual, computed rather than asserted from memory.

        One attempt at ``value_max + headroom`` raw characters renders past the
        cap on a 1.10x payload, which is why it was declined.
        """
        from probos.cognitive.swe_harness.tool_call import _shrink

        page = _crlf_markdown(RAW)
        value = _envelope(page)
        first = str(_shrink(value, value_max=300, list_keep=8, dict_keep=40, depth=0))
        assert len(first) <= LIVE_CAP
        headroom = LIVE_CAP - len(first)
        single = str(
            _shrink(value, value_max=300 + headroom, list_keep=8, dict_keep=40, depth=0)
        )
        assert len(single) > LIVE_CAP, (
            "the single optimistic attempt must overshoot, or this suite is "
            "not exercising the defect"
        )
        assert len(first) < LIVE_CAP * 0.1, "and the fallback really was tiny"

    def test_the_container_rung_ladder_is_what_fits_a_wide_payload(self) -> None:
        """The allowance search runs INSIDE a chosen container ration, so the
        ladder has to pick the rung first.

        Asserted on the RETAINED RECORD COUNT, which is the only thing that
        distinguishes the rungs. Review mutation-checked the first version by
        collapsing the ladder to ``((2, 3),)``: it still passed, because two
        records and an elision marker satisfy every weaker assertion.
        """
        wide = {
            "results": [
                {"id": i, "title": f"result number {i}", "score": i * 0.5}
                for i in range(1_000)
            ]
        }
        retained = {}
        for cap in (150, 200, 300, 600):
            rendered = render_tool_output(wide, max_chars=cap)
            assert len(rendered) <= cap, f"cap {cap} exceeded"
            assert "more items" in rendered, f"cap {cap} lost the ration marker"
            retained[cap] = sum(1 for i in range(1_000) if f"'id': {i}" in rendered)

        assert retained == {150: 2, 200: 2, 300: 4, 600: 8}, (
            f"the rungs must widen with the cap; got {retained}. A single-rung "
            f"ladder returns 2 records at every cap."
        )

    def test_a_short_opaque_scalar_is_never_replaced_by_a_longer_marker(self) -> None:
        """Found by this suite, after the allowance search made it reachable.

        ``'1.43.67'`` carries no whitespace, so it reads as opaque — and
        ``<elided 7 chars>`` costs 16 characters to replace 7. At a zero
        allowance that inflated the floor render enough that every larger
        allowance measured SHORTER and was rejected by the grow-must-not-shrink
        guard, so the search returned the floor and PyPI's version field was
        gone. ``_truncate_leaf`` had this rule; the elision path did not.
        """
        out = {"version": "1.43.67", "sha": "a" * 12, "bulk": "R" * 190_000}
        rendered = render_tool_output(out, max_chars=LIVE_CAP)

        assert "'version': '1.43.67'" in rendered
        assert f"'sha': '{'a' * 12}'" in rendered
        assert "<elided 190000 chars>" in rendered, "the real bulk still goes"

    def test_the_model_receives_it_through_the_real_consumers(self) -> None:
        """Both of them. ``from_tool_result`` is the producer boundary; the
        model sees ``build_tool_result_messages`` and the AD-1151 trace sees
        ``build_tool_trace_payload``. Review pointed out the first version
        stopped at the producer and proved nothing about either consumer.
        """
        from probos.cognitive.swe_harness.agentic_loop import (
            build_tool_result_messages,
            build_tool_trace_payload,
            resolve_tool_trace_bounds,
        )
        from probos.cognitive.swe_harness.tool_call import (
            ToolCallRequest,
            ToolResultBlock,
        )
        from probos.config import AgenticLoopConfig

        page = _crlf_markdown(RAW)
        tcr = ToolCallResult.from_tool_result(
            "call-1", ToolResult(output=_envelope(page)), 1.0, max_chars=LIVE_CAP
        )
        assert not tcr.is_error
        assert len(tcr.output) > LIVE_CAP * 0.85

        cfg = AgenticLoopConfig(tool_result_max_chars=LIVE_CAP)
        message = build_tool_result_messages(
            [ToolResultBlock(result=tcr)],
            max_chars=cfg.tool_result_max_chars,
            head_chars=cfg.tool_result_head_chars,
            tail_chars=cfg.tool_result_tail_chars,
        )[0]
        assert message["content"] == tcr.output, (
            "the AD-1148 slicer must not cut what the renderer just fitted"
        )

        entries, _blob = build_tool_trace_payload(
            [ToolCallRequest(name="mcp_docs_fetch", id="call-1")],
            [tcr],
            **resolve_tool_trace_bounds(cfg),
        )
        assert entries[0]["output"] == tcr.output
        assert entries[0]["output_chars"] == len(tcr.output)
        assert entries[0]["output_truncated"] is False

    def test_run_python_stdout_is_covered_too(self) -> None:
        """Not an MCP defect. The README read that looped seven times came back
        through ``run_python``'s output dict."""
        out = {
            "stdout": _source_code(23_700),
            "stderr": "",
            "exit_code": 0,
            "success": True,
            "artifacts": [],
        }
        rendered = render_tool_output(out, max_chars=LIVE_CAP)
        assert len(rendered) > LIVE_CAP * 0.85
        assert "'exit_code': 0" in rendered, "the short scalars must still survive"


# ── (2) the bisection stays safe and bounded ───────────────────────────────
class TestBisectionIsSafe:
    @pytest.mark.parametrize("make,expansion", PAYLOADS)
    def test_every_render_respects_its_cap(self, make, expansion) -> None:
        """Including caps too small to carry content, where the final pass
        falls back to whole-leaf elision because the marker is the overflow.

        100 is the floor here because the envelope's own shape costs ~81
        characters; below that no representation of this value exists. See
        :meth:`test_a_cap_below_the_values_own_shape_falls_through`.
        """
        envelope = _envelope(make(RAW))
        for cap in (100, 150, 200, 500, 1_000, 2_000, 6_000, 12_000):
            assert len(render_tool_output(envelope, max_chars=cap)) <= cap, (
                f"cap {cap} exceeded on a {expansion}x payload"
            )

    def test_a_cap_below_the_values_own_shape_falls_through(self) -> None:
        """Documented degrade, not a silent one.

        ``{'content': [{'type': 'text', 'text': '<elided N chars>'}], ...}`` is
        about 81 characters before any payload. Under a cap smaller than that,
        ``render_tool_output`` returns its tightest render and the AD-1148
        character-level bound downstream is the backstop — which is exactly
        what its docstring promises. Pinned so the promise stays true.
        """
        envelope = _envelope(_crlf_markdown(RAW))
        rendered = render_tool_output(envelope, max_chars=40)
        assert len(rendered) > 40
        assert "<elided" in rendered, "and the elision is still counted"

    @pytest.mark.parametrize("make,expansion", PAYLOADS)
    def test_retention_is_monotone_in_the_cap(self, make, expansion) -> None:
        """Up to the search's resolution, which is the honest claim.

        The allowance search has a FIXED probe budget, so two nearby caps can
        land on allowances either side of a step and the larger cap can return
        marginally less. Measured worst case across these fixtures: 4,999 -> 5,000
        dips from 4,999 to 4,963 characters, 0.7%. A one-percent tolerance
        admits that and still fails any real stall - the defect this suite
        exists for returned 88 characters where 6,000 were available.
        """
        envelope = _envelope(make(RAW))
        caps = (500, 1_000, 2_000, 4_999, 5_000, 6_000, 12_000, 30_000)
        lengths = [len(render_tool_output(envelope, max_chars=cap)) for cap in caps]

        for earlier, later in zip(lengths, lengths[1:]):
            assert later >= earlier * 0.99, (
                f"a larger cap returned materially less: {lengths} for {caps}"
            )
        assert lengths[-1] > lengths[0] * 2, "the cap must be load-bearing"

    def test_a_mixed_opaque_payload_reaches_the_step_it_needs(self) -> None:
        """Found by review of the first fix. One 3,000-character opaque value
        among thirty 5,000-character ones makes the render a STEP function:
        below allowance 3,000 everything is a marker, at 3,000 the wanted value
        appears whole, at 5,000 the whole thing explodes.

        Interpolation alone stalled on the lower plateau — measured probes
        195, 383, 565, 741, 912, never reaching 3,000 — so the wanted value was
        lost and RAISING the cap destroyed content that a smaller cap kept.
        """
        payload = {"wanted": "W" * 3_000}
        for i in range(30):
            payload[f"bulk_{i}"] = "B" * 5_000

        for cap in (4_999, 5_000, 6_000, 12_000):
            rendered = render_tool_output(payload, max_chars=cap)
            assert len(rendered) <= cap
            assert "W" * 3_000 in rendered, (
                f"cap {cap} lost the one value that fits; the search stalled "
                f"on the plateau"
            )

    def test_a_medium_opaque_scalar_among_larger_ones_survives(self) -> None:
        """The same shape at identifier scale: a 40-character id among eighty
        64-character digests. Review found the id lost at a 2,741-character
        render while allowance 63 would have kept it."""
        payload = {"identifier": "I" * 40}
        for i in range(80):
            payload[f"sha_{i}"] = f"{i:064d}"

        rendered = render_tool_output(payload, max_chars=LIVE_CAP)
        assert len(rendered) <= LIVE_CAP
        assert "I" * 40 in rendered

    def test_a_rung_whose_zero_allowance_overflows_is_still_searched(self) -> None:
        """A zero allowance is not always the cheapest render.

        At the JSON-recursion boundary a LARGER allowance renders SHORTER: a
        JSON-looking string is walked only while it EXCEEDS the allowance and is
        returned verbatim once it fits, and Python's repr of the walked object
        pads every separator that compact JSON omits. Measured on a 199-key
        compact body: the zero-allowance render is 2,377 characters and the
        verbatim one is 1,982, so every cap in between is reachable only by
        searching past a zero that overflowed. The first version of this fix
        treated that zero as proof the rung was impossible and returned the
        overflowing render.
        """
        inner = json.dumps({f"k{i}": i for i in range(199)}, separators=(",", ":"))
        value = {"body": inner}

        walked = str(_shrink(value, value_max=0, list_keep=8, dict_keep=40, depth=0))
        verbatim = str(
            _shrink(value, value_max=len(inner), list_keep=8, dict_keep=40, depth=0)
        )
        assert len(walked) > len(verbatim), (
            "fixture no longer straddles the boundary: the zero-allowance render "
            f"is {len(walked)} and the verbatim one {len(verbatim)}"
        )

        for cap in (len(verbatim), len(verbatim) + 100, len(walked) - 1):
            rendered = render_tool_output(value, max_chars=cap)
            assert len(rendered) <= cap, (
                f"cap {cap} unreachable; the zero-allowance overflow was taken "
                f"as proof no allowance fits"
            )
            # Either shape is a pass: at these caps the search finds the
            # allowance where the body is returned verbatim, so the payload
            # arrives in JSON syntax rather than Python repr syntax.
            assert '"k0":0' in rendered or "'k0': 0" in rendered, (
                f"cap {cap} lost the payload entirely"
            )

    def test_the_elision_still_reconciles(self) -> None:
        page = _crlf_markdown(RAW)
        rendered = render_tool_output(_envelope(page), max_chars=LIVE_CAP)
        reported = _reported_elision(rendered)
        assert 0 < reported < len(page)
        assert reported < len(page) * 0.6, "most of the page should now survive"

    def test_cost_stays_bounded_with_the_bisection(self) -> None:
        """AD-1151 R3 measured a serialise-per-elision shrink loop at 33 s. The
        bisection adds a FIXED number of renders, not a search that grows."""
        big = {
            f"k{i}": {"vals": list(range(50)), "note": "N" * 5_000}
            for i in range(2_000)
        }
        start = time.perf_counter()
        rendered = render_tool_output(big, max_chars=LIVE_CAP)
        elapsed = time.perf_counter() - start
        assert isinstance(rendered, str)
        assert elapsed < 5.0, f"took {elapsed:.1f}s — this has become a shrink loop"

    def test_a_very_large_payload_is_not_slower(self) -> None:
        """A 200 KB page must cost the same fixed number of walks as a 10 KB one."""
        envelope = _envelope(_crlf_markdown(200_000))
        start = time.perf_counter()
        render_tool_output(envelope, max_chars=LIVE_CAP)
        assert time.perf_counter() - start < 1.0


# ── (3) BF-759's carve-outs are unmoved by the bisection ───────────────────
class TestBf759StillHolds:
    def test_an_opaque_leaf_still_keeps_its_counted_elision(self) -> None:
        import base64

        blob = base64.b64encode(bytes(range(256)) * 78).decode()
        envelope = {
            "content": [{"type": "image", "data": blob, "mimeType": "image/png"}]
        }
        rendered = render_tool_output(envelope, max_chars=LIVE_CAP)
        assert f"<elided {len(blob)} chars>" in rendered
        assert len(rendered) < 200, "bisection must not grow into base64"

    def test_a_tools_own_trailing_marker_still_survives(self) -> None:
        recovery = (
            "\n\n... [truncated: 90000 characters elided from this page read. "
            "Re-run extract_text with a narrower selector to retrieve the "
            "elided region.] ...\n\n"
        )
        out = {"action": "extract_text", "text": _crlf_markdown(8_000) + recovery}
        assert "narrower selector" in render_tool_output(out, max_chars=LIVE_CAP)

    def test_the_pypi_scalar_still_survives(self) -> None:
        payload = {
            "info": {"description": "R" * 190_000, "version": "1.43.67"},
            "releases": {f"1.0.{i}": [{"f": i}] for i in range(1_500)},
        }
        out = {"status_code": 200, "body": json.dumps(payload)}
        rendered = render_tool_output(out, max_chars=LIVE_CAP)
        assert "'version': '1.43.67'" in rendered
        assert len(rendered) <= LIVE_CAP

    def test_unbounded_and_already_fitting_stay_byte_identical(self) -> None:
        out = {"status_code": 200, "body": "ok"}
        assert render_tool_output(out, max_chars=0) == str(out)
        assert render_tool_output(out, max_chars=LIVE_CAP) == str(out)
