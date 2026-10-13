"""BF-889: readable text from an HTML document, standard library only.

``PageReaderAgent`` used to strip tags with ``re.sub(r"<[^>]+>", " ", body)``.
That removes the tags and keeps everything between them, including the whole
of every ``<style>`` and ``<script>`` block, so on a page with inline CSS the
reader's 8,000-character budget was spent on stylesheet text before the
article began (#1515, observed 2026-10-11 on a 24,500-character article).

Dropped, with the reason for each:

- ``script``, ``style``: code, never shown to a reader.
- ``noscript``: fallback shown only with scripting off; on article pages it is
  boilerplate ("please enable JavaScript").
- ``template``: inert markup a script may clone later; never rendered as is.
- ``svg``: a drawing; its text nodes are labels and path titles, not prose.

Deliberately KEPT:

- ``head``: its only text-bearing child left once the elements above are
  dropped is ``title``, which names the page and is worth keeping.
- ``nav``, ``footer``, ``aside``: visible page text, and some pages put real
  content there (a table of contents, citations, the author). Deciding which
  visible text is boilerplate is main-content extraction, a different problem
  whose false positives silently delete article text. A long page is read in
  sections now, so keeping them loses nothing.

Robustness (review round 1, 2026-10-13):

- Decimal character references are bounded before the parser sees them
  (:func:`bound_decimal_references`). ``html.parser`` decodes references, in
  text and in attribute values, with ``html.unescape``, which converts the
  digits with ``int``; CPython refuses a decimal string of more than 4,300
  digits, so one zero-padded reference to ``A`` failed the whole read.
- Skipped elements are tracked as a stack: a close tag also closes the
  skipped elements still open inside it, and a close tag with none of its
  name open is ignored. A plain counter let one unclosed inner element hide
  the rest of the page, and one stray close tag expose text still inside a
  ``<template>``.
- :func:`html_to_text` returns text or raises :class:`HtmlTextError`, nothing
  else. It has no degraded mode: ``html.parser`` internals change between
  CPython versions, and a degraded extraction would hand a model the script
  and style text this module exists to drop. The caller decides:
  ``read_page`` reports that no page was read; ``_strip_tags``, which must
  render search titles and snippets, uses :func:`strip_tags_linear`.

Review round 2 (2026-10-13):

- :func:`strip_tags_linear` recognises a skipped element's tags by their
  whole name (``</scripture>`` does not close ``<script>``) and finds the end
  of its start tag by the HTML tokenizer's attribute rules, so a close tag
  inside a quoted attribute value does not end the element.
- ``/>`` closes any skipped element, in both extractors: an empty element,
  as XML and XHTML read it, and as ``html.parser`` reports it. A browser
  reading text/html ignores it on ``script``, ``style``, ``noscript`` and
  ``template`` and hides the rest of the page up to the close tag; an XHTML
  page then lost its whole article. A page reader prefers recall; the cost
  is that code placed after a self-closed ``<script/>`` is read as text.

Every regex here is matched forward from a position that only increases;
:func:`strip_tags_linear` is a fixed number of such linear passes.
:func:`html_to_text` was measured to grow linearly on the shapes tried
(CPython 3.12.13, review round 1), but its parser is the standard library's
and no timing test pins this.

Layer: ``probos.utils`` is the dependency-free leaf every layer may import.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

#: Elements whose content is never page text. See the module docstring.
SKIPPED_ELEMENTS: frozenset[str] = frozenset(
    {"script", "style", "noscript", "template", "svg"}
)

_WHITESPACE_RE = re.compile(r"\s+")

#: Leading zeros of a decimal reference. The lookahead keeps the last digit,
#: so ``&#000;`` becomes ``&#0;``, which still decodes to U+FFFD.
_LEADING_ZEROS_RE = re.compile(r"&#0+(?=[0-9])")
#: Eight or more significant digits: at least 10,000,000, above U+10FFFF, so
#: ``html.unescape`` decodes it as U+FFFD whatever the digits are.
_OUT_OF_RANGE_REF_RE = re.compile(r"&#[1-9][0-9]{7,}")
_REPLACEMENT_REF = "&#65533"

#: A tag with no ``<`` or ``>`` inside. Unlike ``<[^>]+>``, a run of ``<``
#: cannot make it rescan the rest of the document from every position.
_LINEAR_TAG_RE = re.compile(r"<[^<>]*>")
#: What may follow a tag name in HTML: whitespace, ``/``, ``>``, or the end of
#: the input. ``<scripts>`` and ``</scripture>`` are other names.
_NAME_END = r"(?=[\t\n\f\r />]|\Z)"
#: ASCII-only matching: under plain IGNORECASE, ``i`` also matches U+0130,
#: whose lower case is not a key of ``_SKIPPED_CLOSE_RES``.
_SKIPPED_OPEN_RE = re.compile(
    r"<(" + "|".join(sorted(SKIPPED_ELEMENTS)) + r")" + _NAME_END, re.ASCII | re.IGNORECASE
)
_SKIPPED_CLOSE_RES: dict[str, re.Pattern[str]] = {
    tag: re.compile(f"</{tag}" + _NAME_END, re.ASCII | re.IGNORECASE) for tag in SKIPPED_ELEMENTS
}
#: One step of a tag's attribute list, as the HTML tokenizer reads it: the
#: separators (``gap``), then one attribute. A quote opens a value only after
#: ``=``; in a name or an unquoted value it is an ordinary character. An
#: unterminated quote runs to the end of the input. No nested unbounded repetition.
_ATTRIBUTE_RE = re.compile(
    r"(?P<gap>[\t\n\f\r /]*)"
    r"(?P<attribute>[^\t\n\f\r />][^\t\n\f\r />=]*"
    r"(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:\"[^\"]*\"?|'[^']*'?|[^\t\n\f\r >]*))?)?"
)


class HtmlTextError(ValueError):
    """``html.parser`` rejected the document, so no text was extracted."""


def bound_decimal_references(document: str) -> str:
    """``document`` with every decimal character reference short enough to decode.

    ``html.unescape`` of the result equals ``html.unescape`` of ``document``
    wherever the latter does not raise (pinned by a table test of 406 forms).
    """
    return _OUT_OF_RANGE_REF_RE.sub(
        _REPLACEMENT_REF, _LEADING_ZEROS_RE.sub("&#", document)
    )


class _TextCollector(HTMLParser):
    """Collect character data that lies outside :data:`SKIPPED_ELEMENTS`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        #: The skipped elements open now, innermost last.
        self._open: list[str] = []
        #: How many of each name are on ``_open``, so a close tag with no open
        #: match is recognised without scanning the stack.
        self._counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_ELEMENTS:
            self._open.append(tag)
            self._counts[tag] = self._counts.get(tag, 0) + 1
        # Every tag boundary separates words, as the regex this replaces did:
        # ``<td>a</td><td>b</td>`` must not read as ``ab``.
        self._parts.append(" ")  # word break at an opening tag

    # No ``handle_startendtag``: the stdlib default calls ``handle_starttag``
    # then ``handle_endtag``, so ``<script/>`` is an empty element (XHTML) and
    # the page after it is read. See the module docstring.

    def handle_endtag(self, tag: str) -> None:
        # A close tag with none of its name open is ignored: it must neither
        # hide later words nor close an unrelated skipped element.
        if tag in SKIPPED_ELEMENTS and self._counts.get(tag, 0) > 0:
            # Closing an element closes the skipped elements still open inside
            # it. Each element is popped once, so this is amortised O(1).
            while True:
                top = self._open.pop()
                self._counts[top] -= 1
                if top == tag:
                    break
        self._parts.append(" ")  # word break at a closing tag

    def handle_data(self, data: str) -> None:
        if not self._open:
            self._parts.append(data)

    def text(self) -> str:
        return _WHITESPACE_RE.sub(" ", "".join(self._parts)).strip()


def html_to_text(document: str) -> str:
    """Readable text of ``document``.

    Tags are removed, entities decoded once, whitespace collapsed to single
    spaces, and the content of :data:`SKIPPED_ELEMENTS` dropped. Plain text
    passes through with its whitespace collapsed.

    Returns the text or raises :class:`HtmlTextError`; nothing else. With the
    references bounded, 20,000 fuzzed documents raised nothing on CPython
    3.12, but ``html.parser`` is the standard library's and changes between
    versions, so a rejection is reported, never papered over.
    """
    if not document:
        return ""
    collector = _TextCollector()
    try:
        collector.feed(bound_decimal_references(document))
        collector.close()
    except Exception as exc:
        # Propagate: the caller chooses between an honest failure and the
        # linear strip. Only the length is stated; page text is not logged.
        raise HtmlTextError(f"html.parser rejected {len(document)} characters") from exc
    return collector.text()


def _tag_end(document: str, pos: int) -> tuple[int, bool]:
    """Where the tag whose name ends at ``pos`` ends, and whether it ends in ``/>``.

    Returns the index just past its ``>``, or ``-1`` when the input ends
    inside the tag (an unterminated quote included). Each match starts where
    the previous one ended, and each consumes at least one character or ends
    the loop.
    """
    while True:
        step = _ATTRIBUTE_RE.match(document, pos)
        pos = step.end()
        if pos == len(document):
            return -1, False  # the input ends inside the tag
        if document[pos] == ">":
            return pos + 1, step["attribute"] is None and step["gap"].endswith("/")


def _drop_skipped_linear(document: str) -> str:
    """``document`` without its skipped elements, in linear passes."""
    kept: list[str] = []
    pos = 0
    while match := _SKIPPED_OPEN_RE.search(document, pos):
        kept.append(document[pos : match.start()])
        name = match.group(1).lower()
        content_start, self_closed = _tag_end(document, match.end())
        if content_start == -1:
            return " ".join(kept)  # the input ends inside the start tag: the rest is hidden
        if self_closed:
            pos = content_start  # ``/>``: an empty element, as html_to_text reads it
            continue
        close = _SKIPPED_CLOSE_RES[name].search(document, content_start)
        if close is None:
            return " ".join(kept)  # unclosed: the rest is hidden
        end, _ = _tag_end(document, close.end())
        pos = len(document) if end == -1 else end
    kept.append(document[pos:])
    return " ".join(kept)


def strip_tags_linear(document: str) -> str:
    """Text of ``document`` without a parser, in linear passes: a last resort.

    A skipped element's tags are recognised by their whole name, so
    ``</scripture>`` does not close ``<script>`` and ``</script >`` does. The
    end of each tag is found by the HTML tokenizer's attribute rules, so a
    ``>`` or a close tag inside a quoted attribute value does not end it, and
    a quote opens a value only after ``=``. The element's content then runs to
    the next close tag of its name: how HTML delimits ``script`` and
    ``style``; an approximation for ``noscript``, ``template`` and ``svg``,
    whose content HTML parses (a nested element of the same name ends at the
    first close). ``/>`` closes any of the five (an empty element, as XHTML
    and :func:`html_to_text` read it). When the input ends inside a tag (an
    unterminated quote included) or before the close tag, the rest of the
    document is hidden. This path may lose text. The remaining tags are then
    removed by the simple ``<[^<>]*>`` pass, so a ``>`` inside a quoted
    attribute value of an ordinary tag leaves the rest of that value in the
    text, as the pre-BF-889 regex did; only skipped elements' tags use the
    tokenizer's attribute rules. Whitespace is then collapsed and entities
    decoded, with references bounded first.
    """
    text = _LINEAR_TAG_RE.sub(" ", _drop_skipped_linear(document))
    text = _WHITESPACE_RE.sub(" ", text)
    return html.unescape(bound_decimal_references(text)).strip()
