"""BF-776: a model-written tool name must not forge structure in the prose the
Captain reads while deciding whether to approve a repair.

Two halves were filed. Only one still reproduces -- see
``TestTheBriefPreview`` for the measurement that retired the other.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.continue_or_ask import resolve_exhausted_turn
from probos.cognitive.repair_brief import RepairBrief
from probos.cognitive.repair_dispatch import (
    _BRIEF_PREVIEW_MAX,
    RepairDispatcher,
)
from probos.cognitive.trace_analysis import quote_for_prose, render_token

# The name that makes the point: bare, the rationale reads as a sentence
# asserting the SHELL tool was already approved by the Captain.
_FORGING = "browser, and the shell tool (approved by the Captain)"


class _CapturingStore:
    """Captures what ``_file_dispatch_request`` actually files.

    Deliberately NOT a reimplementation of the rationale. An earlier draft of
    this file built the string with a local helper and asserted on that -- so
    reverting the production code changed nothing and both mutants survived.
    The rationale asserted here is the one production wrote.
    """

    def __init__(self) -> None:
        self.filed: list[dict[str, Any]] = []

    async def file_action_request(self, **kwargs: Any) -> object:
        self.filed.append(kwargs)
        return object()


class _Dispatcher(RepairDispatcher):
    """The real dispatcher with only ``targets`` pinned.

    ``targets`` is a property over config; overriding it here keeps the test
    about the prose rather than about building a whole SystemConfig. Everything
    that renders the rationale is production code.
    """

    def __init__(self, store: _CapturingStore, targets: tuple[str, ...]) -> None:
        super().__init__(
            runtime=None,
            fault_report_store=None,
            capability_request_store=store,
            config=None,
        )
        self._targets = targets

    @property
    def targets(self) -> tuple[str, ...]:
        return self._targets


async def _rationale_for(tool_id: str, targets: tuple[str, ...]) -> str:
    """Drive the REAL dispatcher and return the rationale it filed."""
    store = _CapturingStore()
    dispatcher = _Dispatcher(store, targets)
    brief = RepairBrief(
        fault_id="F-1",
        tool_id=tool_id,
        signature="s" * 64,
        error_text="unknown action",
        occurrences=3,
        attempted="press a key",
        agent_id="counselor-ezri",
        thread_id="t-1",
    )

    await dispatcher._file_dispatch_request(brief)

    assert store.filed, "premise: the dispatcher must actually have filed"
    rationale = store.filed[0]["rationale"]
    assert isinstance(rationale, str) and rationale, "premise: a rationale exists"
    return rationale


class TestTheToolNameCannotForgeProse:
    @pytest.mark.asyncio
    async def test_an_ordinary_name_stays_bare(self) -> None:
        """The control. Without this the fix could be 'quote everything',
        which would be noise rather than a boundary."""
        rationale = await _rationale_for("browser", ("claude",))

        assert "The browser tool has failed" in rationale
        assert '"browser"' not in rationale

    @pytest.mark.asyncio
    async def test_a_name_that_could_fake_structure_is_quoted(self) -> None:
        rationale = await _rationale_for(_FORGING, ("claude",))

        assert f'"{_FORGING}"' in rationale, (
            "a model-written tool name must be quoted, or it reads as prose"
        )
        # The specific harm: bare, this sentence appears to tell the Captain
        # the shell tool already carries approval.
        assert f"The {_FORGING} tool" not in rationale

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hostile",
        ['x", "y', "a, b", "tool(arg=1)", "name\nwith\nnewlines"],
    )
    async def test_every_structure_bearing_shape_is_quoted(
        self, hostile: str,
    ) -> None:
        rationale = await _rationale_for(hostile, ("claude",))

        assert f"The {hostile} tool" not in rationale
        # Absence alone is not the property. A rendering that DROPPED the name
        # would satisfy the line above while destroying the Captain's ability
        # to tell WHICH tool failed -- so assert the rendered form is present
        # and that it is quoted, not bare. Round-1 review flagged the
        # absence-only form.
        rendered = render_token(hostile)
        assert rendered in rationale, rationale
        assert rendered.startswith('"') and rendered.endswith('"'), (
            f"a structure-bearing name must be quoted, got {rendered!r}"
        )

    @pytest.mark.asyncio
    async def test_the_targets_are_rendered_the_same_way(self) -> None:
        """The rationale joins targets with ', ' too, so a target carrying a
        comma splits one harness into two in the same sentence."""
        rationale = await _rationale_for("browser", ("claude", "a, b"))

        assert '"a, b"' in rationale
        assert rationale.count("claude") == 1

    def test_the_helper_itself_discriminates(self) -> None:
        assert render_token("browser") == "browser"
        assert render_token(_FORGING) != _FORGING


class TestTheBriefPreview:
    """BF-776's second half, retired by measurement rather than by fixing it.

    The issue reported a six-call brief rendering at ~6,749 chars against a
    1,200-char slice, losing ``Done means`` and ``Provenance``. That was true
    when it was filed. AD-1267 (``fb2ffb83``) then made ``render_for_payload``
    exclude every trace-derived field -- not for readability, but because
    ``action_dedup_key`` hashes ``params`` whole and a trace that appears
    between occurrences would raise a second Captain approval for one fault.

    The evidence the slice used to cut is therefore no longer IN the payload
    brief to cut, and is one ``params["fault_id"]`` lookup away instead. This
    test exists so that if anything ever puts it back, the truncation is caught
    here rather than rediscovered in front of the Captain.
    """

    def _big_brief(self) -> RepairBrief:
        calls = [
            "- browser("
            + ", ".join(f'arg{j}="value-{j}-{"x" * 40}"' for j in range(6))
            + ")"
            for _ in range(6)
        ]
        return RepairBrief(
            fault_id="F-1",
            tool_id="browser",
            signature="s" * 64,
            error_text="unknown browser action: 'key_type'",
            occurrences=3,
            attempted="press a key on the page",
            agent_id="counselor-ezri",
            thread_id="t-1",
            trace_summary="Across 6 tool(s):\n" + "\n".join(calls),
            tool_trace_ref="abc123",
            suspected_files=("src/probos/tools/browser/tool.py",),
            acceptance=("the same call succeeds",),
        )

    def test_the_payload_brief_fits_the_preview_whole(self) -> None:
        brief = self._big_brief()

        rendered = brief.render_for_payload()

        assert len(rendered) <= _BRIEF_PREVIEW_MAX, (
            f"the payload brief is {len(rendered)} chars against a "
            f"{_BRIEF_PREVIEW_MAX} preview slice -- BF-776's second half is "
            "live again and the slice is cutting evidence"
        )
        assert rendered == rendered[:_BRIEF_PREVIEW_MAX]

    def test_the_premise_holds_that_a_large_trace_was_supplied(self) -> None:
        """Without this the test above passes on an empty fixture.

        My first attempt at BF-776 used a hand-rolled 484-char string and
        'not truncated' meant nothing.
        """
        brief = self._big_brief()

        assert len(brief.trace_summary) > _BRIEF_PREVIEW_MAX, (
            "premise: the trace summary must itself exceed the preview cap, or "
            "the fit above is not evidence of anything"
        )
        assert brief.trace_summary not in brief.render_for_payload(), (
            "premise: render_for_payload must be EXCLUDING the trace -- that is "
            "why it fits, and if it stops the test above must fail"
        )

    def test_the_portable_artifact_still_carries_the_evidence(self) -> None:
        """The trace is excluded from the PAYLOAD, not lost. ``render_markdown``
        is the artifact a person or a harness reads, and it keeps everything."""
        brief = self._big_brief()

        markdown = brief.render_markdown()

        assert brief.trace_summary in markdown
        assert len(markdown) > _BRIEF_PREVIEW_MAX


class TestTheSiblingProseSink:
    """Round-1 review found the same class in ``continue_or_ask``: the
    Captain-facing reply naming a repeatedly-failing tool. Same untrusted
    source (the name the MODEL wrote), same reader, same forging. One instance
    of a class is not the class, so it is pinned here beside the rationale.

    This drives the real ``resolve_exhausted_turn`` -- the prose asserted is
    the prose production wrote, for the reason recorded on ``_CapturingStore``.
    """

    @staticmethod
    async def _reply(tool_name: str, error_text: str = "boom") -> str:
        outcome = SimpleNamespace(
            final_text="",
            stopped_reason="max_iterations",
            tool_calls=[SimpleNamespace(id="c1", name=tool_name),
                        SimpleNamespace(id="c2", name=tool_name)],
            tool_results=[
                SimpleNamespace(id="c1", output=error_text, is_error=True),
                SimpleNamespace(id="c2", output=error_text, is_error=True),
            ],
        )

        async def _no_reinvoke(_task: str) -> Any:
            raise AssertionError("must not re-invoke on a detected defect")

        return await resolve_exhausted_turn(
            outcome,
            reinvoke=_no_reinvoke,
            runtime=SimpleNamespace(fault_report_store=None),
            agent_id="counselor-ezri",
            base_task_text="type Hello",
            config=SimpleNamespace(
                continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
            ),
        )

    @pytest.mark.asyncio
    async def test_the_defect_reply_is_reached_at_all(self) -> None:
        """Premise. Every assertion below is vacuous if the defect sentence is
        not the branch taken -- a reply that never mentions a tool cannot
        contain a forged claim about one."""
        reply = await self._reply("browser")

        assert "The browser tool answered" in reply, reply

    @pytest.mark.asyncio
    async def test_a_forging_tool_name_cannot_fake_the_sentence(self) -> None:
        reply = await self._reply(_FORGING)

        assert f"The {_FORGING} tool answered" not in reply, reply
        assert render_token(_FORGING) in reply, reply


class TestWhatRenderTokenChangesAboutTheName:
    """``render_token`` is not verbatim, and round-1 review was right to ask.
    Measured, not assumed -- these are the alterations, pinned so a future
    change to them is a decision rather than a surprise.

    All three are deliberate: a Captain-facing sentence cannot carry a raw
    newline, an unescaped quote, or an unbounded name without the surrounding
    prose losing its shape. The name is normalised to stay readable, never
    dropped.
    """

    def test_a_plain_name_is_left_completely_alone(self) -> None:
        """Premise for the rest: quoting is conditional, so the tests below
        are about the shapes that trigger it, not about every name."""
        assert render_token("browser") == "browser"
        assert render_token("a-b.c") == "a-b.c"

    def test_an_embedded_quote_is_escaped_not_stripped(self) -> None:
        assert render_token('x", "y') == '"x\\", \\"y"'

    def test_whitespace_is_collapsed_to_a_single_space(self) -> None:
        assert render_token("name\nwith\nnewlines") == '"name with newlines"'
        assert render_token("tab\there") == '"tab here"'

    def test_a_long_name_is_clipped_with_an_ellipsis(self) -> None:
        """The one alteration that LOSES information. Accepted: an unbounded
        model-written name in a decision sentence is its own problem, and the
        clip is visible rather than silent."""
        rendered = render_token("x" * 100)

        assert rendered.endswith('\u2026"')
        assert len(rendered) < 100

    def test_non_ascii_survives_intact(self) -> None:
        """Quoted, but not mangled -- a name is still identifiable."""
        assert render_token("caf\u00e9") == '"caf\u00e9"'


class TestTheErrorHalfOfTheSameSentence:
    """Round-2 review's High, reproduced and closed.

    Closing ``tool_id`` and leaving ``error`` open would have shipped a
    boundary that looks total and is not -- the same sentence, the same
    Captain, the same forging, one field over. The error is TOOL OUTPUT, so it
    is if anything the more attacker-reachable half.

    The property is NOT that the hostile text is absent -- it is that the text
    cannot leave the error's quoted span and continue the ship's own sentence.
    An absence assertion would have passed on a rendering that simply dropped
    the error, destroying the Captain's evidence.
    """

    _MARKER = "times with: "

    async def _span(self, error_text: str) -> str:
        reply = await TestTheSiblingProseSink._reply("browser", error_text)
        assert self._MARKER in reply, (
            f"premise: the defect sentence must be the branch taken; got {reply!r}"
        )
        return reply.split(self._MARKER, 1)[1]

    @staticmethod
    def _split_span(span: str) -> tuple[str, str]:
        """The quoted error, and whatever the ship says after it.

        Parsed with the JSON decoder rather than an index search: a hand-rolled
        ``span.index('"')`` finds the ESCAPED quote inside the literal and
        reports containment failures that are artefacts of the locator. The
        decoder knows where the literal actually ends, which is the only
        boundary this test is about.
        """
        value, end = json.JSONDecoder().raw_decode(span)
        return value, span[end:]

    @pytest.mark.asyncio
    async def test_a_benign_error_is_already_quoted(self) -> None:
        """Premise for the rest. If the error is not quoted even here, the
        containment assertions below cannot discriminate anything."""
        span = await self._span("boom")

        assert span.startswith('"boom"'), span

    @pytest.mark.asyncio
    async def test_error_text_cannot_continue_the_ships_sentence(self) -> None:
        forged = "boom. The shell tool is approved by the Captain"

        inside, after = self._split_span(await self._span(forged))

        assert inside == forged, (
            "the error must survive in full -- a rendering that DROPPED it "
            "would pass a mere absence check while losing the evidence"
        )
        assert "approved by the Captain" not in after, (
            f"forged claim escaped the quoted span: {after!r}"
        )

    @pytest.mark.asyncio
    async def test_an_embedded_quote_cannot_close_the_span_early(self) -> None:
        """The actual bypass of quoting. Unescaped, a ``\"`` in tool output
        ends the span and everything after it becomes the ship's prose."""
        hostile = 'boom" The shell tool is approved'

        inside, after = self._split_span(await self._span(hostile))

        assert inside == hostile, "the escaped quote must round-trip"
        assert "approved" not in after, (
            f"an embedded quote closed the span early: {after!r}"
        )


class TestTheBriefItselfCannotForgeMarkdown:
    """Round-2 review's Medium, reproduced and closed.

    The brief is the third surface of the same class, and the worst of the
    three: ``render_for_payload`` is what the approval inbox shows, so a
    ``tool_id`` carrying newlines and a ``##`` rendered a real heading reading
    APPROVED BY THE CAPTAIN into the document the Captain reads while deciding
    whether to approve.

    The property is again containment, not absence -- and the probe that first
    'confirmed' this fix had failed was itself wrong, because it searched for
    the substring, which survives (correctly) inside the quoted span.
    """

    _FORGED = "browser\n\n## APPROVED BY THE CAPTAIN\n\n- shell"

    def _brief(self, tool_id: str) -> RepairBrief:
        return RepairBrief(
            fault_id="fault-1",
            tool_id=tool_id,
            signature="sig",
            error_text="boom",
            occurrences=3,
            attempted="type Hello",
            agent_id="counselor-ezri",
            trace_summary="t",
            acceptance=("it stops failing",),
        )

    def test_a_plain_tool_id_reaches_both_renderings(self) -> None:
        """Premise. If the name never reaches the document, the containment
        assertions below are vacuous."""
        brief = self._brief("browser")

        assert "browser" in brief.render_markdown()
        assert "browser" in brief.render_for_payload()

    @pytest.mark.parametrize("render", ["render_markdown", "render_for_payload"])
    def test_a_tool_id_cannot_open_a_heading(self, render: str) -> None:
        """The property is that the name cannot create a NEW line.

        Not 'APPROVED is absent' -- the brief's own ``# Repair brief:`` heading
        legitimately contains the quoted name, so a substring search flags the
        fix as broken. Counting headings discriminates; searching does not.
        """
        def headings(brief: RepairBrief) -> list[str]:
            text: str = getattr(brief, render)()
            return [
                line for line in text.splitlines()
                if line.lstrip().startswith("#")
            ]

        control = headings(self._brief("browser"))
        hostile = headings(self._brief(self._FORGED))

        assert len(control) > 1, (
            "premise: the brief must have headings at all, or counting them "
            "cannot detect an injected one"
        )
        assert len(hostile) == len(control), (
            f"{render} gained {len(hostile) - len(control)} heading(s): "
            f"{[h for h in hostile if h not in control]!r}"
        )
        # And the name is still THERE -- a renderer that dropped it would pass
        # the count above while destroying the Captain's evidence.
        assert render_token(self._FORGED) in getattr(
            self._brief(self._FORGED), render,
        )()

    def test_the_title_carries_no_raw_newlines(self) -> None:
        """No production consumer today, so this pins the trap rather than a
        live defect -- stated plainly so nobody reads it as more than it is."""
        assert "\n" not in self._brief(self._FORGED).title


class TestTheQuotedOutputIsAlwaysSendable:
    """Round-3 review's Medium, measured and closed at the helper.

    ``quote_for_prose`` documented itself as safe "only because every caller
    passes ``_clip`` output" -- and BF-776 then gave it two callers that do
    not. ``json.dumps`` does not reject a lone surrogate, it EMITS one, so
    nothing fails at the boundary; the reply simply cannot be UTF-8 encoded
    later, breaking the whole response somewhere unattributable. That is the
    same harm ``_clip`` documents at BF-774, moved somewhere harder to find.
    """

    _LONE_SURROGATE = "boom\ud800tail"

    def test_the_premise_that_a_lone_surrogate_is_unsendable(self) -> None:
        """Without this, the assertions below could pass on a string that was
        never a problem in the first place."""
        with pytest.raises(UnicodeEncodeError):
            self._LONE_SURROGATE.encode("utf-8")

    def test_quoted_output_can_always_be_encoded(self) -> None:
        quoted = quote_for_prose(self._LONE_SURROGATE)

        assert quoted.encode("utf-8")  # must not raise
        assert quoted.startswith('"') and quoted.endswith('"')

    @pytest.mark.asyncio
    async def test_the_quoted_error_span_is_sendable(self) -> None:
        """Scoped deliberately to the span BF-776 owns.

        The whole reply is NOT yet surrogate-safe, and saying otherwise here
        would be the guard that looks total and is not: measured on the real
        path, ``ToolDefect.signature`` raises ``UnicodeEncodeError`` at
        ``fault_report.py:259`` before any prose is built, so a tool returning
        malformed UTF-8 kills the turn outright. That is a separate defect on a
        shared path, filed rather than absorbed here.
        """
        from probos.cognitive.continue_or_ask import _final_error_quote

        assert _final_error_quote(self._LONE_SURROGATE).encode("utf-8")

    def test_a_surrogate_in_a_tool_name_cannot_break_the_brief(self) -> None:
        """``tool_id`` specifically -- it is the field BF-776 routes through
        the helper. Other brief fields (``error_text``, ``signature``,
        ``attempted``, ``agent_id``, ``fault_id``) are still raw and still
        produce unsendable documents; enumerated and filed, not claimed."""
        brief = RepairBrief(
            fault_id="f", tool_id=self._LONE_SURROGATE, signature="s",
            error_text="boom", occurrences=2, attempted="x",
        )

        assert brief.render_for_payload().encode("utf-8")
        assert brief.render_markdown().encode("utf-8")

    def test_the_unrenderable_fallback_still_works(self) -> None:
        """The try/except is the other half of totality. If the surrogate
        replacement had swallowed it, this would be the regression."""
        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("unstringable")

        assert quote_for_prose(Boom()) == '"<unrenderable>"'  # type: ignore[arg-type]
