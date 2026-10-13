"""BF-889 (#1515): read_page reads a long page in sections, and says so.

Observed 2026-10-11: ``read_page`` kept the first 8,000 characters of a
tag-stripped page, counted inline CSS as page text, reported no cut, and gave
the caller no way to read on. Ezri's four reads of a 24,500-character article
each summarised its introduction.

Every test below that matters is premised on the fixture reproducing that:
``TestTheFixtureDiscriminates`` fails first if it stops doing so.
"""

from __future__ import annotations

import html
import itertools
import logging
import math
import re
import threading
from html.parser import HTMLParser
from unittest.mock import MagicMock

import pytest

from probos.agents.utility import web_agents
from probos.agents.utility.web_agents import (
    _SECTION_CHARS,
    FetchOutcome,
    PageReaderAgent,
    TextSection,
    WeatherAgent,
    WebSearchAgent,
    _parse_offset,
    _section_header,
    _text_section,
    _with_section_notice,
)
from probos.cognitive.agentic_dispatch import _MESH_TOOL_SPECS
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.types import IntentMessage
from probos.utils import html_text
from probos.utils.html_text import (
    SKIPPED_ELEMENTS,
    HtmlTextError,
    bound_decimal_references,
    html_to_text,
    strip_tags_linear,
)

# ── fixture: about 20 KB of inline CSS, then about 25 KB of article ──

_OPENING = "MASS opening sentence: agents search a space of system designs."
_CLOSING = "Closing sentence of the article, end marker ZQX."
_CSS_RULE = ".nav-item{color:#123456;margin:0 auto;}\n"
_PARAGRAPH = "<p>" + ("Body text about multi-agent system search. " * 20) + "</p>"
_SECTION_NOTE = "one section of a longer text"


def _long_page() -> str:
    return (
        "<html><head><title>MASS article</title>"
        "<style>" + _CSS_RULE * 500 + "</style>"
        "<script>var tracking = 'SCRIPT_LEAK';</script></head><body>"
        f"<h1>{_OPENING}</h1>" + _PARAGRAPH * 30 + f"<p>{_CLOSING}</p>"
        "</body></html>"
    )


def _old_extraction(document: str) -> str:
    """PageReaderAgent.perceive before BF-889, kept to prove the fixture bites."""
    text = re.sub(r"<[^>]+>", " ", document)
    return re.sub(r"\s+", " ", text).strip()


class _Runtime:
    intent_bus = object()


class _RecordingLLM:
    """Records every prompt; not a MagicMock, so a renamed field cannot pass."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request, **_kw):
        self.prompts.append(f"{request.prompt}\n{request.system_prompt or ''}")
        resp = MagicMock()
        resp.content = "SUMMARY"
        resp.tokens_used = 10
        resp.tier = "fast"
        return resp


def _agent(cls: type, monkeypatch, outcome: FetchOutcome, fetches: list | None = None):
    async def _fetch(_runtime, _url):
        if fetches is not None:
            fetches.append(_url)
        return outcome

    monkeypatch.setattr(web_agents, "_mesh_fetch_detailed", _fetch)
    agent = cls(agent_id="bf889")
    agent._runtime = _Runtime()
    agent._llm_client = _RecordingLLM()
    return agent


async def _read(agent, **params):
    obs = await agent.perceive(IntentMessage(intent="read_page", params=params))
    decision = await agent.decide(obs)
    return obs, await agent.act(decision)


# ── premises ─────────────────────────────────────────────────────


class TestTheFixtureDiscriminates:
    def test_the_page_has_about_20kb_of_css_then_about_25kb_of_article(self):
        assert 19_000 <= len(_CSS_RULE * 500) <= 22_000
        assert 24_000 <= len(html_to_text(_long_page())) <= 28_000

    def test_the_old_extraction_loses_the_opening_to_css(self):
        """If this fails, the fixture no longer reproduces #1515."""
        old = _old_extraction(_long_page())[:_SECTION_CHARS]
        assert "nav-item" in old
        assert _OPENING not in old


# ── html_to_text ─────────────────────────────────────────────────

#: 4,302 digits that denote "A": two more than CPython converts by default.
_LONG_REF_A = "&#" + "0" * 4300 + "65;"
#: Script and style content that must never reach extracted or model text.
_HIDDEN_BLOCKS = "<script>HIDDEN_SCRIPT()</script><style>.HIDDEN_STYLE{}</style>"


def _reject(self, data):
    """Stands in for a parser rejection; no input is known to cause one on 3.12."""
    raise AssertionError("unknown status keyword")


class TestHtmlToText:
    def test_the_opening_lands_inside_the_first_section(self):
        assert _OPENING in html_to_text(_long_page())[:_SECTION_CHARS]

    def test_style_and_script_content_is_dropped(self):
        text = html_to_text(_long_page())
        assert "nav-item" not in text
        assert "SCRIPT_LEAK" not in text

    def test_the_title_is_kept(self):
        assert html_to_text(_long_page()).startswith("MASS article ")

    @pytest.mark.parametrize("tag", sorted(SKIPPED_ELEMENTS))
    def test_each_skipped_element_drops_only_its_content(self, tag):
        page = f"<p>before</p><{tag}>HIDDEN</{tag}><p>after</p>"
        assert html_to_text(page) == "before after"

    def test_nav_and_footer_text_is_kept(self):
        page = "<nav>Contents</nav><p>x</p><footer>Cite as</footer>"
        assert html_to_text(page) == "Contents x Cite as"

    def test_an_unclosed_script_hides_only_what_follows_it(self):
        assert html_to_text("<p>Before</p><script>var x = 'secret';") == "Before"

    def test_tag_names_are_case_insensitive(self):
        assert html_to_text("<P>Hi</P><STYLE>body{color:red}</STYLE>") == "Hi"

    def test_a_stray_close_tag_does_not_hide_later_text(self):
        assert html_to_text("<p>a</p></style><p>b</p>") == "a b"

    def test_nested_and_self_closing_svg(self):
        assert html_to_text("<svg><svg><text>L</text></svg>x</svg>after") == "after"
        assert html_to_text("<p>a</p><svg/><p>after</p>") == "a after"

    @pytest.mark.parametrize(
        "tag",
        ['<script type="text/javascript" src="a.js"/>', "<style type='text/css'/>", "<noscript/>", "<template/>"],
    )
    def test_a_self_closed_skipped_element_is_empty_as_in_xhtml(self, tag):
        """Round-2 recall correction: ``/>`` closes it, so the article is read."""
        assert html_to_text(f"<head>{tag}</head><body><p>ARTICLE_TEXT</p></body>") == "ARTICLE_TEXT"
        assert html_to_text(f"<body><p>BEFORE</p>{tag}<p>AFTER</p></body>") == "BEFORE AFTER"
        assert html_to_text("a<br/>b") == "a b"

    def test_entities_are_decoded_exactly_once(self):
        page = "<p>&lt;b&gt; &amp;lt; caf&eacute;</p>"
        assert html_to_text(page) == "<b> &lt; caf\u00e9"

    def test_adjacent_cells_stay_separate_words(self):
        assert html_to_text("<td>a</td><td>b</td>") == "a b"

    def test_every_opening_and_closing_tag_separates_words(self):
        """As the regex it replaces did: ``<br>`` has no closing tag, and
        ``</i>`` has no opening tag after it, so each boundary is pinned alone."""
        assert html_to_text("a<br>b") == "a b"
        assert html_to_text("<i>a</i>b") == "a b"

    def test_plain_text_and_a_bare_less_than_pass_through(self):
        assert html_to_text("1<2 and 3>2") == "1<2 and 3>2"

    def test_empty_input_is_empty(self):
        assert html_to_text("") == ""

    def test_a_parser_failure_raises_html_text_error(self, monkeypatch):
        """No degraded mode: a rejection is reported to the caller, typed."""
        monkeypatch.setattr(html_text._TextCollector, "feed", _reject)
        with pytest.raises(HtmlTextError) as caught:
            html_to_text("<p>a &amp; b</p>")
        assert isinstance(caught.value, ValueError)
        assert isinstance(caught.value.__cause__, AssertionError)


class TestCharacterReferences:
    def test_a_4302_digit_reference_in_text_decodes(self):
        page = f"<p>short {_LONG_REF_A} readable</p>"
        parser = HTMLParser(convert_charrefs=True)
        with pytest.raises(ValueError):  # premise: the unbounded parser fails
            parser.feed(page)
            parser.close()
        assert html_to_text(page) == "short A readable"

    def test_a_4302_digit_reference_in_an_attribute_value_does_not_fail(self):
        page = f'<p title="{_LONG_REF_A}">VISIBLE</p>{_HIDDEN_BLOCKS}<p>after</p>'
        parser = HTMLParser(convert_charrefs=True)
        with pytest.raises(ValueError):  # premise: the unbounded parser fails
            parser.feed(page)
            parser.close()
        assert html_to_text(page) == "VISIBLE after"

    def test_an_overlong_reference_is_the_replacement_character(self):
        nines = "&#" + "9" * 5000 + ";"
        with pytest.raises(ValueError):  # premise: html.unescape fails on it
            html.unescape(nines)
        assert html_to_text(f"<p>{nines}</p>") == "�"
        assert html.unescape("&#12345678;") == "�"  # premise: 8 digits is out of range
        assert html_to_text("<p>&#12345678;</p>") == "�"
        assert html_to_text("<p>&#" + "0" * 5000 + ";</p>") == "�"

    def test_the_reference_bound_agrees_with_html_unescape(self):
        """One table: 20 values x 5 zero paddings x 4 terminators, plus 6 long
        runs html.unescape still accepts. The bound must change nothing that
        html.unescape can decode."""
        values = [
            0, 1, 9, 10, 65, 127, 128, 129, 159, 160, 0xD7FF, 0xD800, 0xDFFF,
            0xE000, 0x10FFFF, 0x110000, 9_999_999, 10_000_000, 12_345_678,
            99_999_999_999,
        ]
        checked = 0
        for value, pad, tail in itertools.product(values, (0, 1, 5, 20, 100), (";", "", " x", "abc")):
            source = f"a &#{'0' * pad}{value}{tail} b"
            assert html.unescape(bound_decimal_references(source)) == html.unescape(source), source
            checked += 1
        for digits in (8, 9, 20, 100, 4000, 4300):
            source = "&#" + "7" * digits + ";"
            assert html.unescape(bound_decimal_references(source)) == html.unescape(source) == "�"
            checked += 1
        assert checked == 406


class TestSkippedElementsNest:
    def test_text_after_a_closed_svg_survives_an_unclosed_noscript_inside_it(self):
        page = "<p>B</p><svg><noscript></svg><p>A</p>"
        assert _old_extraction(page) == "B A"  # premise: the regex kept A
        assert html_to_text(page) == "B A"

    def test_a_close_tag_of_another_skipped_element_does_not_expose_template_text(self):
        page = "<template><p>in</p></noscript><p>H</p></template><p>A</p>"
        assert "noscript" in SKIPPED_ELEMENTS  # premise: the stray close is a skipped name
        assert html_to_text(page) == "A"

    def test_closing_an_outer_element_closes_the_ones_open_inside_it(self):
        assert html_to_text("<template><svg><noscript></template>Y") == "Y"

    def test_a_close_tag_with_nothing_left_open_is_ignored(self):
        assert html_to_text("<svg>x</svg>a</svg>b") == "a b"


class TestTheLinearStrip:
    def test_it_drops_script_and_style_and_decodes_bounded_references(self):
        page = (
            "<p>a</p><style>.nav-item{color:red}</style><script>track()</script>"
            f"<p>b &amp; c {_LONG_REF_A}</p>"
        )
        assert strip_tags_linear(page) == "a b & c A"

    def test_an_unclosed_script_hides_the_rest(self):
        assert strip_tags_linear("a<SCRIPT>b") == "a"

    @pytest.mark.parametrize(
        "page",
        ["<script>HIDDEN</scripture> VISIBLE", "<style>HIDDEN</stylesheet> VISIBLE"],
    )
    def test_a_close_tag_of_a_longer_name_does_not_close(self, page):
        assert html_to_text(page) == ""  # premise: the parser reads the rest as code
        assert strip_tags_linear(page) == ""

    def test_a_longer_tag_name_is_not_a_skipped_element(self):
        page = "<scripts>a</scripts> <svgx>b</svgx>"
        assert html_to_text(page) == "a b"  # premise
        assert strip_tags_linear(page) == "a b"

    @pytest.mark.parametrize(
        "page", ["<script-x>VISIBLE</script-x>", "<style.x>VISIBLE</style.x>", "<noscript:x>VISIBLE</noscript:x>"]
    )
    def test_a_punctuated_tag_name_is_not_a_skipped_element(self, page):
        assert html_to_text(page) == "VISIBLE"  # premise: a custom element; its text is kept
        assert strip_tags_linear(page) == "VISIBLE"

    def test_a_close_tag_with_a_punctuated_suffix_does_not_close(self):
        page = "<script>HIDDEN</script-x>MORE</script>VISIBLE"
        assert html_to_text(page) == "VISIBLE"  # premise
        assert strip_tags_linear(page) == "VISIBLE"

    @pytest.mark.parametrize(
        "page",
        [
            '<script data-x="</script>">HIDDEN</script> VISIBLE',
            "<style data-x='</style>'>HIDDEN</style> VISIBLE",
            '<script data-x="a></script>c">HIDDEN</script> VISIBLE',
        ],
    )
    def test_a_close_tag_or_gt_inside_a_quoted_value_does_not_end_the_tag(self, page):
        assert html_to_text(page) == "VISIBLE"  # premise: the parser agrees
        assert strip_tags_linear(page) == "VISIBLE"

    @pytest.mark.parametrize(
        "page",
        [
            '<script a" b="x>y</script>">HIDDEN</script> VISIBLE',
            '<script a=b=" c="x>y</script>">HIDDEN</script> VISIBLE',
        ],
    )
    def test_a_quote_opens_a_value_only_after_equals(self, page):
        """A quote in a name or an unquoted value is a character; pairing it
        would end the tag at ``x>`` and show HIDDEN."""
        assert html_to_text(page) == "VISIBLE"  # premise: the parser agrees
        assert strip_tags_linear(page) == "VISIBLE"

    def test_a_close_tag_with_whitespace_still_closes(self):
        page = "<script>HIDDEN</script >VISIBLE<STYLE>HIDDEN</STYLE\n>AFTER"
        assert html_to_text(page) == "VISIBLE AFTER"  # premise
        assert strip_tags_linear(page) == "VISIBLE AFTER"

    def test_a_quoted_gt_in_a_close_tag_does_not_end_it(self):
        assert strip_tags_linear('<script>HIDDEN</script data-x=">">VISIBLE') == "VISIBLE"

    @pytest.mark.parametrize(
        "page",
        ['a<script data-x="x>HIDDEN</script>VISIBLE', "a<style data-x='x>HIDDEN</style>VISIBLE"],
    )
    def test_an_unterminated_quote_hides_the_rest(self, page):
        """The input ends inside the start tag, as an unclosed element hides the rest."""
        assert strip_tags_linear(page) == "a"

    @pytest.mark.parametrize(
        "tag",
        ['<script type="text/javascript" src="a.js"/>', "<style type='text/css'/>", "<noscript/>", "<template/>"],
    )
    def test_a_self_closed_skipped_element_is_empty_as_in_xhtml(self, tag):
        """The fallback reads ``/>`` as :func:`html_to_text` does."""
        assert strip_tags_linear(f"<head>{tag}</head><body><p>ARTICLE_TEXT</p></body>") == "ARTICLE_TEXT"
        assert strip_tags_linear(f"<body><p>BEFORE</p>{tag}<p>AFTER</p></body>") == "BEFORE AFTER"

    def test_self_closing_ends_an_svg(self):
        assert strip_tags_linear("a<svg/>b") == "a b"
        assert strip_tags_linear("a<svg a/>b") == "a b"
        assert strip_tags_linear("a<svg a=b/>HIDDEN</svg>c") == "a c"  # ``b/`` is a value

    def test_code_after_a_self_closed_script_is_read_as_text(self):
        """The accepted cost of the XHTML reading (Blind spot 11), in both paths."""
        assert html_to_text("a<script/>CODE()</script>b") == "a CODE() b"
        assert strip_tags_linear("a<script/>CODE()</script>b") == "a CODE() b"

    def test_start_tags_are_scanned_forward_only(self, monkeypatch):
        """20,000 unclosed ``<script "`` tags: a regex retried from every
        ``<`` would rescan the rest each time. The scan's matches must start at
        strictly increasing positions, one per attribute."""
        starts: list[int] = []
        real = html_text._ATTRIBUTE_RE

        class _Recording:
            def match(self, document, pos):
                starts.append(pos)
                return real.match(document, pos)

        monkeypatch.setattr(html_text, "_ATTRIBUTE_RE", _Recording())
        page = "a" + '<script "' * 20_000
        assert strip_tags_linear(page) == "a"
        assert 0 < len(starts) <= page.count(" ") + 1
        assert all(b > a for a, b in zip(starts, starts[1:]))


class TestStripTagsDelegation:
    def test_ordinary_fragments_read_as_before_and_two_differences_are_fixes(self):
        import html as _html

        def old_strip_tags(fragment: str) -> str:
            # exact copy of the base _strip_tags (web_agents.py:252-255)
            text = re.sub(r"<[^>]+>", " ", fragment)
            return _html.unescape(re.sub(r"\s+", " ", text)).strip()

        identical = [
            "plain",
            "<b>Hello</b> world",
            "<a href='x'><b>Hello</b> <i>world</i></a>",
            "Tom &amp; Jerry",
            "It&#x27;s &quot;fine&quot;",
            "a &lt;b&gt; c",
            "caf&#233; &#8212; ok",
            "&nbsp;lead and trail&nbsp;",
            "a < b",
            "Line one\n\tLine two",
            "one<br>two<br/>three",
            "&foo; bar",
            "R&D and Q&A",
            "",
        ]
        for fragment in identical:
            assert web_agents._strip_tags(fragment) == old_strip_tags(fragment), fragment
        assert web_agents._strip_tags("a &lt;b&gt; c") == "a <b> c"

        fixed = [
            ("x&nbsp;y", "x\xa0y", "x y"),
            ("if a < b and c > d then", "if a d then", "if a < b and c > d then"),
            (
                "Learn how to <b>use</b> the &amp; operator &#8230; in <b>Python</b>&nbsp;3",
                "Learn how to use the & operator … in Python \xa03",
                "Learn how to use the & operator … in Python 3",
            ),
        ]
        for fragment, expected_old, expected_new in fixed:
            assert old_strip_tags(fragment) == expected_old, fragment
            assert web_agents._strip_tags(fragment) == expected_new, fragment

    def test_strip_tags_falls_back_to_the_linear_strip_with_a_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(html_text._TextCollector, "feed", _reject)
        caplog.set_level(logging.WARNING, logger="probos.agents.utility.web_agents")
        fragment = "<b>Tom</b> &amp; Jerry<style>.x{}</style>"
        assert web_agents._strip_tags(fragment) == "Tom & Jerry"
        assert "BF-889" in caplog.text

    def test_the_fallback_hides_script_behind_a_quoted_false_close(self, monkeypatch, caplog):
        monkeypatch.setattr(html_text._TextCollector, "feed", _reject)
        caplog.set_level(logging.WARNING, logger="probos.agents.utility.web_agents")
        fragment = '<b>Tom</b><script data-x="</script>">HIDDEN()</script> Jerry'
        assert web_agents._strip_tags(fragment) == "Tom Jerry"
        assert "BF-889" in caplog.text


# ── sections ─────────────────────────────────────────────────────


class TestSections:
    def test_a_short_text_is_one_whole_section_with_no_notice(self):
        section = _text_section("short page")
        assert section == TextSection(text="short page", start=0, end=10, total=10)
        assert section.is_whole
        assert _with_section_notice(section) == "short page"
        assert _section_header(section, FetchOutcome(body="x")) == ""

    def test_a_short_text_read_from_an_offset_inside_it_is_a_section(self):
        """Only a read from offset 0 of a text that fits is whole."""
        section = _text_section("abcde", 4)
        assert not section.is_whole
        assert "characters 4 to 5 of 5" in _with_section_notice(section)
        header = _section_header(section, FetchOutcome(body="x"))
        assert header.startswith("[read_page section: characters 4 to 5 of 5 ")

    def test_exactly_one_section_is_whole_and_one_more_char_is_not(self):
        assert _text_section("a" * _SECTION_CHARS).is_whole
        assert not _text_section("a" * (_SECTION_CHARS + 1)).is_whole

    def test_a_cut_first_section_tells_the_model_after_the_text(self):
        text = _with_section_notice(_text_section("a" * 20_000))
        assert text.startswith("a" * _SECTION_CHARS + "\n\n")
        assert "characters 0 to 8000 of 20000" in text[_SECTION_CHARS:]

    def test_a_later_section_is_never_whole_even_at_the_end(self):
        section = _text_section("a" * 20_000, 16_000)
        assert (section.start, section.end, section.total) == (16_000, 20_000, 20_000)
        assert section.reaches_end
        assert not section.is_whole
        assert "characters 16000 to 20000 of 20000" in _with_section_notice(section)

    def test_the_header_gives_the_next_offset_while_more_remains(self):
        header = _section_header(_text_section("a" * 20_000), FetchOutcome(body="x"))
        assert "More follows" in header
        assert "offset=8000 " in header

    def test_the_last_section_says_it_reaches_the_end(self):
        header = _section_header(
            _text_section("a" * 20_000, 16_000), FetchOutcome(body="x")
        )
        assert "reaches the end of the page text" in header
        assert "offset=" not in header

    def test_the_last_section_of_a_fetch_capped_page_does_not_claim_the_end(self):
        outcome = FetchOutcome(body="x", truncated=True, total_bytes=2_000_000)
        header = _section_header(_text_section("a" * 20_000, 16_000), outcome)
        assert "the page itself goes on" in header
        assert "reaches the end of the page text" not in header

    def test_no_notice_or_header_reads_as_a_capability_gap(self):
        fields = {"start": 8000, "end": 16000, "total": 24512}
        for template in (
            web_agents._SECTION_NOTICE,
            web_agents._SECTION_HEADER_MORE,
            web_agents._SECTION_HEADER_END,
            web_agents._SECTION_HEADER_END_FETCH_CUT,
        ):
            assert _CAPABILITY_GAP_RE.search(template.format(**fields)) is None

    def test_the_section_notice_is_distinct_from_the_fetch_cap_notice(self):
        """BF-807 tests key on "partial document"; the two facts must not merge."""
        assert "partial document" not in web_agents._SECTION_NOTICE


class TestParseOffset:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, 0), ("", 0), ("  ", 0), (0, 0), (8000, 8000),
            ("8000", 8000), (" 16000 ", 16000), (8000.0, 8000),
        ],
    )
    def test_accepted(self, raw, expected):
        assert _parse_offset(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            -1, "-1", "8,000", "abc", True, False, 1.5, float("nan"),
            "\u00b2", "1" * 10, [8000],
        ],
    )
    def test_refused(self, raw):
        assert _parse_offset(raw) is None


# ── PageReaderAgent, perceive -> model -> caller ─────────────────


class TestPageReaderReadsInSections:
    async def test_the_first_read_starts_at_the_article_not_the_css(self, monkeypatch):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=_long_page(), status_code=200))
        obs, _result = await _read(agent, url="https://e.co/mass")
        assert _OPENING in obs["fetched_content"]
        assert "nav-item" not in obs["fetched_content"]

    async def test_the_cut_reaches_the_summarising_model(self, monkeypatch):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=_long_page(), status_code=200))
        await _read(agent, url="https://e.co/mass")
        assert any(_SECTION_NOTE in p for p in agent._llm_client.prompts)

    async def test_the_caller_gets_the_next_offset_ahead_of_the_summary(self, monkeypatch):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=_long_page(), status_code=200))
        _obs, result = await _read(agent, url="https://e.co/mass")
        assert result["success"] is True
        assert result["result"].startswith("[read_page section: characters 0 to 8000 of ")
        assert "offset=8000 " in result["result"][:400]
        assert result["result"].endswith("\n\nSUMMARY")

    async def test_the_end_is_reachable_by_following_the_offsets(self, monkeypatch):
        """Offsets travel as strings, as the AD-869 [MESH ...] tag sends them."""
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=_long_page(), status_code=200))
        total = len(html_to_text(_long_page()))
        offset, reads, seen = "0", 0, []
        while True:
            obs, result = await _read(agent, url="https://e.co/mass", offset=offset)
            reads += 1
            seen.append(obs["fetched_content"])
            match = re.search(r"offset=(\d+) ", result["result"])
            if match is None:
                break
            offset = match.group(1)
            assert reads < 10, "the offsets never reached the end"
        assert reads == math.ceil(total / _SECTION_CHARS)
        assert _CLOSING in seen[-1]
        assert "reaches the end of the page text" in result["result"]

    async def test_an_integer_offset_works_through_handle_intent(self, monkeypatch):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=_long_page(), status_code=200))
        res = await agent.handle_intent(
            IntentMessage(intent="read_page", params={"url": "https://e.co/mass", "offset": 8000})
        )
        assert res is not None and res.success is True
        assert str(res.result).startswith("[read_page section: characters 8000 to 16000 of ")

    async def test_a_short_page_reads_exactly_as_before(self, monkeypatch):
        """Read from offset 0, exactly as before in shape only: no section
        notice, no header, the result is the summary alone. The model input is
        the extracted text."""
        agent = _agent(
            PageReaderAgent, monkeypatch,
            FetchOutcome(body="<html><body>short page text</body></html>", status_code=200),
        )
        obs, result = await _read(agent, url="https://e.co/short")
        assert obs["fetched_content"] == "short page text"
        assert "result_header" not in obs
        assert result == {"success": True, "result": "SUMMARY"}
        assert not any(_SECTION_NOTE in p for p in agent._llm_client.prompts)

    @pytest.mark.parametrize("bad", ["-5", "abc", "8,000", True, -1])
    async def test_a_bad_offset_is_refused_before_any_fetch(self, monkeypatch, bad):
        fetches: list = []
        agent = _agent(
            PageReaderAgent, monkeypatch, FetchOutcome(body="<p>x</p>", status_code=200), fetches
        )
        _obs, result = await _read(agent, url="https://e.co/x", offset=bad)
        assert fetches == []
        assert agent._llm_client.prompts == []
        assert result["success"] is False
        assert "offset must be a whole number" in result["error"]
        assert _CAPABILITY_GAP_RE.search(result["error"]) is None

    async def test_an_offset_at_the_end_is_refused_and_one_before_it_reads(self, monkeypatch):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body="<p>short</p>", status_code=200))
        _obs, at_end = await _read(agent, url="https://e.co/x", offset=5)
        assert at_end["success"] is False
        assert "past the end of the page text (5 characters)" in at_end["error"]
        assert _CAPABILITY_GAP_RE.search(at_end["error"]) is None
        assert agent._llm_client.prompts == []

        _obs, last_char = await _read(agent, url="https://e.co/x", offset=4)
        assert last_char["success"] is True
        assert last_char["result"].startswith("[read_page section: characters 4 to 5 of 5 ")

    async def test_a_page_with_no_readable_text_fails_honestly(self, monkeypatch):
        agent = _agent(
            PageReaderAgent, monkeypatch,
            FetchOutcome(body="<html><script>app()</script></html>", status_code=200),
        )
        _obs, result = await _read(agent, url="https://e.co/spa")
        assert result["success"] is False
        assert "no readable text" in result["error"]
        assert _CAPABILITY_GAP_RE.search(result["error"]) is None
        assert agent._llm_client.prompts == []

    async def test_a_failed_model_call_carries_no_section_header(self, monkeypatch):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=_long_page(), status_code=200))
        agent._llm_client = None
        _obs, result = await _read(agent, url="https://e.co/mass")
        assert result["success"] is False
        assert "result" not in result

    async def test_a_fetch_capped_long_page_keeps_both_facts(self, monkeypatch):
        agent = _agent(
            PageReaderAgent, monkeypatch,
            FetchOutcome(body=_long_page(), status_code=200, truncated=True, total_bytes=2_000_000),
        )
        obs, result = await _read(agent, url="https://e.co/mass", offset=24_000)
        assert "partial document" in obs["fetched_content"]
        assert _SECTION_NOTE in obs["fetched_content"]
        assert "the page itself goes on" in result["result"]

    async def test_a_parser_failure_fails_the_read_honestly(self, monkeypatch, caplog):
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body="<p>x</p>", status_code=200))
        monkeypatch.setattr(html_text._TextCollector, "feed", _reject)
        caplog.set_level(logging.WARNING, logger="probos.agents.utility.web_agents")
        _obs, result = await _read(agent, url="https://e.co/secret-token")
        assert result == {
            "success": False,
            "error": "no page was read: the page could not be read as HTML",
        }
        assert agent._llm_client.prompts == []
        assert _CAPABILITY_GAP_RE.search(result["error"]) is None
        assert "BF-889" in caplog.text
        assert "secret-token" not in caplog.text

    async def test_a_4302_digit_attribute_reference_reads_through_the_agent(self, monkeypatch):
        body = (
            f"<html><head>{_HIDDEN_BLOCKS}</head>"
            f'<body><a title="{_LONG_REF_A}">VISIBLE</a></body></html>'
        )
        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body=body, status_code=200))
        obs, result = await _read(agent, url="https://e.co/ref")
        assert obs["fetched_content"] == "VISIBLE"
        assert result == {"success": True, "result": "SUMMARY"}
        assert agent._llm_client.prompts
        assert not any("HIDDEN" in p for p in agent._llm_client.prompts)

    async def test_extraction_runs_off_the_event_loop(self, monkeypatch):
        threads: list[int] = []
        real = web_agents.html_to_text

        def _recording(document: str) -> str:
            threads.append(threading.get_ident())
            return real(document)

        agent = _agent(PageReaderAgent, monkeypatch, FetchOutcome(body="<p>x</p>", status_code=200))
        monkeypatch.setattr(web_agents, "html_to_text", _recording)
        obs, _result = await _read(agent, url="https://e.co/x")
        assert obs["fetched_content"] == "x"
        assert len(threads) == 1
        assert threads[0] != threading.get_ident()  # this coroutine runs on the loop's thread


# ── the other readers in web_agents state their cut too ──────────


class TestTheOtherReadersStateTheirCut:
    async def test_weather_states_a_cut_body(self, monkeypatch):
        body = '{"current_condition":[{"temp_C":"12"}],"pad":"' + "x" * 20_000 + '"}'
        agent = _agent(WeatherAgent, monkeypatch, FetchOutcome(body=body, status_code=200))
        obs = await agent.perceive(IntentMessage(intent="get_weather", params={"location": "London"}))
        assert obs["fetched_content"].startswith('{"current_condition"')
        assert "characters 0 to 8000 of " in obs["fetched_content"]

    async def test_a_bang_landing_page_drops_css_and_states_its_cut(self, monkeypatch):
        agent = _agent(
            WebSearchAgent, monkeypatch,
            FetchOutcome(body=_long_page(), status_code=200, final_url="https://en.wikipedia.org/wiki/MASS"),
        )
        obs = await agent.perceive(IntentMessage(intent="web_search", params={"query": "!w mass"}))
        assert _OPENING in obs["fetched_content"]
        assert _SECTION_NOTE in obs["fetched_content"]

    async def test_a_long_search_result_block_states_its_cut(self, monkeypatch):
        result = (
            '<div class="result"><h2><a class="result__a" href="https://e.co/{i}">'
            'Title {i}</a></h2><a class="result__snippet">' + "s" * 4000 + "</a></div>"
        )
        page = "".join(result.format(i=i) for i in range(3))
        agent = _agent(
            WebSearchAgent, monkeypatch,
            FetchOutcome(body=page, status_code=200, final_url="https://html.duckduckgo.com/html/?q=x"),
        )
        obs = await agent.perceive(IntentMessage(intent="web_search", params={"query": "x"}))
        assert obs["fetched_content"].startswith("Result 1:\nTitle: Title 0\n")
        assert _SECTION_NOTE in obs["fetched_content"]

    @pytest.mark.parametrize(
        "cls,params,body,final_url",
        [
            (WeatherAgent, {"location": "London"}, '{"current_condition":[]}', None),
            (WebSearchAgent, {"query": "!w x"}, "<html><body>landing</body></html>", "https://en.wikipedia.org/wiki/X"),
        ],
    )
    async def test_a_short_body_gets_no_section_notice(self, monkeypatch, cls, params, body, final_url):
        agent = _agent(cls, monkeypatch, FetchOutcome(body=body, status_code=200, final_url=final_url))
        obs = await agent.perceive(IntentMessage(intent="x", params=params))
        assert obs["fetched_content"]
        assert _SECTION_NOTE not in obs["fetched_content"]

    async def test_a_reader_that_sets_no_header_returns_the_summary_alone(self, monkeypatch):
        """BF-772 keeps one decide/act for every fetch-gated reader, so the
        read_page header pass-through lives in the mixin; a reader that never
        sets the key gets no header: its result is the model's output alone."""
        agent = _agent(WeatherAgent, monkeypatch, FetchOutcome(body='{"current_condition":[]}', status_code=200))
        obs = await agent.perceive(IntentMessage(intent="get_weather", params={"location": "London"}))
        assert "result_header" not in obs
        result = await agent.act(await agent.decide(obs))
        assert result == {"success": True, "result": "SUMMARY"}


# ── what the caller is told ──────────────────────────────────────


def _read_page_spec() -> tuple:
    for spec in _MESH_TOOL_SPECS:
        if spec[0] == "read_page":
            return spec
    raise AssertionError("read_page is missing from _MESH_TOOL_SPECS")


class TestTheCallerIsToldTheContract:
    def test_offset_is_an_optional_non_negative_integer(self):
        schema = _read_page_spec()[4]
        assert schema["required"] == ["url"]
        assert schema["properties"]["url"] == {"type": "string"}
        assert schema["properties"]["offset"]["type"] == "integer"
        assert schema["properties"]["offset"]["minimum"] == 0

    def test_the_tool_description_names_sections_and_offset(self):
        description = _read_page_spec()[3]
        assert "section" in description
        assert "offset" in description

    def test_the_usage_hint_teaches_offset_in_a_tag_that_parses(self):
        hint = PageReaderAgent.intent_descriptors[0].usage_hint
        assert hint.startswith("[MESH read_page url=<url>] ")
        assert "[MESH read_page url=<url> offset=<n>]" in hint
        assert _CAPABILITY_GAP_RE.search(hint) is None
        parsed = DmSanityGate().extract_mesh_read(
            "[MESH read_page url=https://x.test/a?b=c offset=8000]"
        )
        assert parsed == ("read_page", {"url": "https://x.test/a?b=c", "offset": "8000"})

    def test_the_intent_descriptor_params_are_unchanged(self):
        """The federation MCP server marks every descriptor param REQUIRED
        (mcp_server.py ``_project_tools_from_descriptors``). Adding ``offset``
        there would break an MCP client that exposes read_page."""
        assert PageReaderAgent.intent_descriptors[0].params == {"url": "<url>"}
