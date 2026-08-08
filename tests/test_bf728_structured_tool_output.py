"""BF-728 (#1182): a big structured tool result is flattened shape-first.

The Captain asked for the current version of the top 15 PyPI packages. The
agent fetched all 15 successfully — 16 ``http_fetch`` calls, every one
``is_error=False``, every one HTTP 200. It then answered from training data
(``boto3 1.34.131``, nine minor versions behind the ``1.43.67`` it had just
fetched) and explained itself with *"this sandbox has no network access"* —
true of the ``run_python`` sandbox, irrelevant to the mesh tool it had just
used sixteen times.

Nothing errored. Nothing warned. The fault machinery detects refusals
(AD-1168/1169/1170); this was a success that did the wrong thing.

Cause: a dict tool output was flattened with a bare ``str()`` and only then cut
by character position. PyPI's JSON is 1–3 MB dominated by ``info.description``
(the whole README) and ``releases`` (every file of every historical release).
``info.version`` sits between them, so head/tail truncation kept the start of
the README and the end of the release history and threw away the answer.

Two design points are load-bearing and each was arrived at by being wrong first:

* **A long string is recursed into, not elided,** when it parses as JSON. For
  ``http_fetch`` the ``body`` member IS the payload; eliding it would trade one
  silent data loss for another.
* **Dict entries are rationed by KIND, not position.** A first-N rule cut
  ``version`` off the end, because PyPI serves ``info`` with alphabetically
  ordered keys. Scalars are cheap and identifying, so all of them are kept and
  only nested containers are rationed.
"""

from __future__ import annotations

import json
import time

import pytest

from probos.cognitive.swe_harness.agentic_loop import truncate_tool_output
from probos.cognitive.swe_harness.tool_call import ToolCallResult, render_tool_output


class _Result:
    """Minimal stand-in for the AD-423a ToolResult shape."""

    def __init__(self, output, error=None) -> None:
        self.output = output
        self.error = error


def _pypi_shaped(*, version: str = "1.43.67", releases: int = 1500) -> dict:
    """A faithful reduction of the real payload: one huge README, a huge
    release map, and the wanted scalar sitting between them under a key that
    sorts near the end of its object."""
    return {
        "info": {
            "author": "Amazon Web Services",
            "classifiers": [f"Programming Language :: Python :: 3.{i}" for i in range(12)],
            "description": "R" * 190_000,
            "summary": "The AWS SDK for Python",
            "version": version,
            "yanked": False,
        },
        "last_serial": 39805198,
        "releases": {
            f"1.0.{i}": [{"filename": f"boto3-1.0.{i}.tar.gz", "size": 1234}]
            for i in range(releases)
        },
        "urls": [{"filename": "boto3.whl", "size": 999}],
    }


def _as_http_fetch_output(payload: dict) -> dict:
    """Exactly what HttpFetchAgent returns: the JSON arrives as a STRING."""
    return {
        "url": "https://pypi.org/pypi/boto3/json",
        "status_code": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload),
        "body_length": len(json.dumps(payload)),
        "rate_limit_delay": 0.0,
    }


# ── (1) the headline ───────────────────────────────────────────────────────
class TestTheAnswerSurvives:
    def test_the_wanted_scalar_survives_a_multi_megabyte_payload(self) -> None:
        """Fails before the fix. This is the Captain's actual question."""
        out = _as_http_fetch_output(_pypi_shaped())
        rendered = render_tool_output(out, max_chars=6000)

        assert "'version': '1.43.67'" in rendered, (
            "the version field was lost again — this is the whole defect"
        )

    def test_the_old_path_really_did_lose_it(self) -> None:
        """The counterfactual, so this suite proves the fix is load-bearing
        rather than asserting something that was already true."""
        out = _as_http_fetch_output(_pypi_shaped())
        old = truncate_tool_output(
            str(out), max_chars=6000, head_chars=4000, tail_chars=2000
        )
        assert "'version'" not in old

    def test_the_result_actually_fits_the_budget(self) -> None:
        out = _as_http_fetch_output(_pypi_shaped())
        assert len(render_tool_output(out, max_chars=6000)) <= 6000

    def test_it_survives_even_when_the_key_sorts_last(self) -> None:
        """PyPI orders ``info`` alphabetically, so ``version`` is near the end.
        A position-based dict bound cut it off — measured, not theorised."""
        payload = _pypi_shaped()
        payload["info"] = {
            **{f"aaa_{i}": f"filler-{i}" for i in range(40)},
            "version": "9.9.9",
        }
        rendered = render_tool_output(_as_http_fetch_output(payload), max_chars=6000)
        assert "'version': '9.9.9'" in rendered


# ── (2) embedded JSON is recursed, not elided ──────────────────────────────
class TestEmbeddedJson:
    def test_a_json_body_string_is_walked_not_thrown_away(self) -> None:
        """For http_fetch the body IS the payload. Eliding it would swap one
        silent loss for another."""
        out = _as_http_fetch_output({"deep": {"needle": "FOUND"}})
        out["body"] = json.dumps({"deep": {"needle": "FOUND"}, "bulk": "B" * 500_000})
        rendered = render_tool_output(out, max_chars=6000)
        assert "FOUND" in rendered

    def test_a_long_non_json_string_is_elided_with_its_size(self) -> None:
        out = {"log": "L" * 500_000, "status": 200}
        rendered = render_tool_output(out, max_chars=2000)
        assert "elided" in rendered
        assert "500000" in rendered, "the marker must say how much went"
        assert "'status': 200" in rendered, "a short scalar must survive"

    def test_a_string_that_only_looks_like_json_is_elided_not_raised(self) -> None:
        out = {"body": "{not really json at all" + "x" * 500_000}
        rendered = render_tool_output(out, max_chars=2000)
        assert "elided" in rendered


# ── (3) default-OFF byte-identity ──────────────────────────────────────────
class TestNothingElseChanges:
    def test_unbounded_is_byte_identical_to_str(self) -> None:
        out = _as_http_fetch_output(_pypi_shaped())
        assert render_tool_output(out, max_chars=0) == str(out)

    def test_a_small_result_is_byte_identical_to_str(self) -> None:
        out = {"status": 200, "body": "ok"}
        assert render_tool_output(out, max_chars=6000) == str(out)

    @pytest.mark.parametrize("value", ["text", 42, None, True, 3.5])
    def test_a_non_container_is_byte_identical_to_str(self, value) -> None:
        assert render_tool_output(value, max_chars=10) == str(value)

    def test_from_tool_result_defaults_to_the_old_coercion(self) -> None:
        """Every existing caller passes no bound and must be unaffected."""
        out = _as_http_fetch_output(_pypi_shaped())
        tcr = ToolCallResult.from_tool_result("id-1", _Result(out), 1.0)
        assert tcr.output == str(out)

    def test_from_tool_result_bounds_when_asked(self) -> None:
        out = _as_http_fetch_output(_pypi_shaped())
        tcr = ToolCallResult.from_tool_result("id-1", _Result(out), 1.0, max_chars=6000)
        assert "'version': '1.43.67'" in tcr.output
        assert len(tcr.output) < len(str(out))

    def test_a_string_output_is_never_restructured(self) -> None:
        """Only structured outputs take the new path; text tools are untouched."""
        tcr = ToolCallResult.from_tool_result(
            "id-1", _Result("A" * 50_000), 1.0, max_chars=100
        )
        assert tcr.output == "A" * 50_000

    def test_an_error_result_is_unchanged(self) -> None:
        tcr = ToolCallResult.from_tool_result(
            "id-1", _Result(None, error="boom"), 1.0, max_chars=100
        )
        assert tcr.is_error and tcr.output == "boom"


# ── (4) it must never raise, and never become a shrink loop ────────────────
class TestHostileInputAndCost:
    def test_a_self_referential_structure_does_not_hang_or_raise(self) -> None:
        loop: dict = {"a": 1}
        loop["self"] = loop
        rendered = render_tool_output(loop, max_chars=200)
        assert isinstance(rendered, str)

    def test_a_hostile_repr_degrades_instead_of_raising(self) -> None:
        class _Nasty:
            def __repr__(self):
                raise RuntimeError("no repr for you")

        rendered = render_tool_output({"x": _Nasty()}, max_chars=100)
        assert isinstance(rendered, str)

    def test_deep_nesting_is_bounded(self) -> None:
        deep: dict = {"end": "BOTTOM"}
        for _ in range(200):
            deep = {"n": deep}
        rendered = render_tool_output(deep, max_chars=500)
        assert isinstance(rendered, str)
        assert len(rendered) <= 500 * 4

    def test_cost_is_bounded_passes_not_a_loop(self) -> None:
        """AD-1151 R3 measured a serialise-per-elision shrink loop at 33 s for
        2000 entries, synchronously inside an async method. This runs at most
        three renders, so a large structure must stay fast."""
        big = {f"k{i}": {"vals": list(range(50)), "note": "N" * 5_000} for i in range(2_000)}
        start = time.perf_counter()
        rendered = render_tool_output(big, max_chars=6000)
        elapsed = time.perf_counter() - start
        assert isinstance(rendered, str)
        assert elapsed < 5.0, f"took {elapsed:.1f}s — this has become a shrink loop"
