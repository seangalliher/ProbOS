"""BF-856: malformed tool output must not be able to break this path.

Filed off the BF-776 review waves. Three items, all measured before fixing:

1. ``ToolDefect.signature`` raised ``UnicodeEncodeError`` on a lone surrogate
   and killed the exhausted turn before any reply was built.
2. Five ``RepairBrief`` fields rendered documents that could not be encoded.
3. ``render_token`` clipped at 80, so two distinct long names rendered alike.

The through-line: a buggy tool -- not a hostile one -- was enough for all three.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.repair_brief import RepairBrief
from probos.cognitive.continue_or_ask import resolve_exhausted_turn
from probos.cognitive.trace_analysis import render_token
from probos.fault_report import ToolDefect, error_signature, normalise_error

#: A lone high surrogate. Not representable in UTF-8, which is the whole point.
LONE_SURROGATE = "boom\ud800tail"


def test_the_premise_that_this_input_is_unencodable() -> None:
    """Every assertion in this file is vacuous if the fixture encodes cleanly."""
    with pytest.raises(UnicodeEncodeError):
        LONE_SURROGATE.encode("utf-8")


class TestTheSignatureSurvivesMalformedOutput:
    """Item 1. This is the one that killed the turn outright."""

    def test_error_signature_does_not_raise(self) -> None:
        assert len(error_signature(
            tool_id="browser", error_text=LONE_SURROGATE,
        )) == 64

    def test_the_defect_property_does_not_raise(self) -> None:
        defect = ToolDefect(
            tool_id="browser", error_text=LONE_SURROGATE, count=2,
        )

        assert len(defect.signature) == 64

    def test_the_two_paths_stay_byte_identical(self) -> None:
        """``ToolDefect.signature`` documents itself as byte-identical to
        ``error_signature``. They now share one helper, so a drift is not
        reachable by editing one -- but a drift would be invisible until faults
        silently stopped coalescing, so it is pinned rather than trusted.
        """
        defect = ToolDefect(
            tool_id="browser", error_text=LONE_SURROGATE, count=2,
        )
        assert defect.error_key == normalise_error(LONE_SURROGATE) != "", (
            "premise: error_key is ALWAYS overwritten in __post_init__ from "
            "error_text -- if it were empty the comparison below would be "
            "between two different materials and would prove nothing"
        )

        assert defect.signature == error_signature(
            tool_id="browser", error_text=LONE_SURROGATE,
        )

    @pytest.mark.parametrize(
        "material",
        ["browser|timeout", "", "caf\u00e9|x", "a" * 500],
    )
    def test_no_stored_signature_moves(self, material: str) -> None:
        """``"replace"`` is a no-op on well-formed input, so every signature
        already in ``fault_reports.db`` still matches. If this failed, the fix
        would need a migration -- and silently split every existing fault."""
        assert (
            hashlib.sha256(material.encode("utf-8")).hexdigest()
            == hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()
        )

    @pytest.mark.asyncio
    async def test_the_exhausted_turn_still_produces_a_reply(self) -> None:
        """The end-to-end failure: this used to raise out of
        ``resolve_exhausted_turn`` before any prose was built."""
        outcome = SimpleNamespace(
            final_text="", stopped_reason="max_iterations",
            tool_calls=[SimpleNamespace(id="1", name="browser"),
                        SimpleNamespace(id="2", name="browser")],
            tool_results=[
                SimpleNamespace(id="1", output=LONE_SURROGATE, is_error=True),
                SimpleNamespace(id="2", output=LONE_SURROGATE, is_error=True),
            ],
        )

        async def _no_reinvoke(_task: str) -> Any:
            raise AssertionError("must not re-invoke on a detected defect")

        reply = await resolve_exhausted_turn(
            outcome,
            reinvoke=_no_reinvoke,
            runtime=SimpleNamespace(fault_report_store=None),
            agent_id="counselor-ezri",
            base_task_text="type Hello",
            config=SimpleNamespace(
                continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
            ),
        )

        assert reply.encode("utf-8")


class TestEveryBriefFieldRendersSomethingSendable:
    """Item 2. Scrubbed once where the lines become a document, so a field
    added later is covered by construction -- per-field scrubbing is how one
    gets missed."""

    _FIELDS = ("fault_id", "tool_id", "signature", "error_text",
               "attempted", "agent_id", "trace_summary")

    def _brief(self, field: str) -> RepairBrief:
        kwargs: dict[str, Any] = {name: "safe" for name in self._FIELDS}
        kwargs.pop("signature", None)  # a read-only property on the dataclass
        kwargs["signature"] = "safe"
        kwargs["occurrences"] = 2
        kwargs[field] = f"x{LONE_SURROGATE}y"
        return RepairBrief(**kwargs)

    def test_the_premise_that_a_clean_brief_renders(self) -> None:
        kwargs: dict[str, Any] = {name: "safe" for name in self._FIELDS}
        kwargs["occurrences"] = 2
        brief = RepairBrief(**kwargs)

        assert "safe" in brief.render_markdown()

    @pytest.mark.parametrize("field", _FIELDS)
    def test_markdown_is_sendable(self, field: str) -> None:
        assert self._brief(field).render_markdown().encode("utf-8")

    @pytest.mark.parametrize("field", _FIELDS)
    def test_the_approval_payload_is_sendable(self, field: str) -> None:
        assert self._brief(field).render_for_payload().encode("utf-8")

    @pytest.mark.parametrize("field", _FIELDS)
    def test_the_title_is_sendable(self, field: str) -> None:
        assert self._brief(field).title.encode("utf-8")

    def test_the_markdown_keeps_its_newlines(self) -> None:
        """The scrub must not collapse whitespace -- this is markdown, and the
        newlines ARE the structure. A whitespace-collapsing scrub would pass
        every assertion above while destroying the document."""
        kwargs: dict[str, Any] = {name: "safe" for name in self._FIELDS}
        kwargs["occurrences"] = 2

        assert RepairBrief(**kwargs).render_markdown().count("\n") > 5


class TestTwoLongNamesStayDistinguishable:
    """Item 3. The clip is the one alteration that loses information."""

    def test_the_premise_that_these_names_are_clipped(self) -> None:
        """If they were short enough to survive whole, distinctness would be
        trivial and the assertions below would prove nothing."""
        rendered = render_token("x" * 100)

        assert "\u2026" in rendered and len(rendered) < 100

    def test_names_differing_past_the_bound_render_differently(self) -> None:
        assert render_token("x" * 100) != render_token("x" * 99 + "y")

    def test_names_differing_at_the_boundary_render_differently(self) -> None:
        assert render_token("x" * 79 + "ABC") != render_token("x" * 79 + "DEF")

    def test_short_names_are_untouched(self) -> None:
        """The disambiguator must not fire on names that were never clipped."""
        assert render_token("browser") == "browser"
        assert render_token("a-b.c") == "a-b.c"

    def test_the_suffix_is_stable_across_renders(self) -> None:
        assert render_token("x" * 100) == render_token("x" * 100)

    def test_the_rendered_bound_is_the_clip_plus_the_digest(self) -> None:
        """Review flagged that the cap was implicit and that this change moves
        it. Pinned explicitly so the new bound is a stated contract rather than
        an accident: unclipped names stay at the clip bound, clipped ones carry
        six more characters and no more.
        """
        from probos.cognitive.trace_analysis import _ARG_VALUE_MAX

        unclipped = render_token("x" * _ARG_VALUE_MAX)
        clipped = render_token("x" * 500)

        assert len(unclipped) == _ARG_VALUE_MAX, (
            "premise: a name at exactly the bound must NOT be clipped, or the "
            "comparison below is between two clipped values"
        )
        assert len(clipped) == _ARG_VALUE_MAX + 6 + 2, (
            f"clip + 6-hex digest + 2 quote chars; got {len(clipped)}"
        )

    def test_a_raising_str_still_renders(self) -> None:
        """The disambiguator sits on a path whose contract is not to raise."""
        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("unstringable")

        assert render_token(Boom()) == '"<unrenderable>"'
