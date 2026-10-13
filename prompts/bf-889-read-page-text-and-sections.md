# BF-889 (#1515): read_page extracts real text, states its cut, and reads a long page in sections

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12 — execution found two failed premises: the BF-772 no-shadow guard (header pass-through moved into `_FetchGatedMixin`, 2c/2f) and the AD-1258 offer digest (carve-out, Section 3b). Revised: 2c, 2f, 3b (new), the 4a header test and one reference, Mutation table, Milestones, Acceptance Criteria, Blind spots, Verified/Absence; cache-rationale correction; _strip_tags claim fix; review round 1 (2026-10-13, findings F1-F5 on candidate tree `f68d7672`): bounded character references, a stack of skipped elements, no regex degradation (`HtmlTextError`: `read_page` fails honestly, `_strip_tags` uses a linear strip), extraction off the event loop, precise "short page" wording, `test_perceive_strips_html` reaches `perceive`. Revised: Contract, Blind spots, Section 1, 2a, 2c (one comment), 2d, 2f, 4a, 4b, Validation, Mutation table, Milestones, Tracking, Acceptance Criteria, Verified; linear-claim precision; review round 2 (2026-10-13, findings M1, L1, L2a, L2b on candidate tree `f53ea84e`): the linear strip recognises skipped-element tags by whole name and ends those tags by the HTML tokenizer's attribute rules (other tags are removed by a simple pass), `/>` closes only `svg` in both extractors, the attribute-reference tests carry script/style content, short-page claims qualified to offset 0, "linear passes" wording. Revised: Contract, Blind spots (10), Section 1, 2f docstring, 4a (+17 tests, 2 changed), Validation, Mutation table (+H17-H24), Milestones, Check expectations, Tracking, Acceptance Criteria, Verified; round-2 recall correction (2026-10-13, found by the orchestrator executing round 2: the parser-path `handle_startendtag` hid the whole article after an XHTML `<script src="a.js"/>`): `/>` now closes all five skipped elements in both extractors (XHTML reading; recall over browser fidelity), `_TextCollector.handle_startendtag` and `_SELF_CLOSING_SKIPPED` removed. Revised: Contract, Blind spots (11), Section 1, 4a (+8 tests, 2 replaced), Validation, Mutation table (H22, H23 rewritten), Milestones, Acceptance Criteria, Verified; tracker precision; review round 3 lows.

**Status:** Ready for Builder. Base `origin/main` `4efabdfb`.
**Number:** BF-889 (exists, #1515). No AD: no new AD or BF is allocated by this prompt.
**Dependencies:** none. No new dependency (stdlib `html.parser` only).
**Estimated tests:** 118 new in one new file (review round 2: +17; round-2 recall correction: +8; review round 3: +4), plus 1 existing test updated (`tests/test_utility_agents.py`) and the AD-1258 offer oracle carved out for BF-889's one change (`tests/test_ad1258_self_knowledge.py`, Section 3b; no new test there).

**One line:** `read_page` stops counting CSS and script as page text, tells both the summarising model and the caller when it cut the page, and takes an optional `offset` so a crew agent can read the rest.

---

## Problem

Observed live 2026-10-11 (see `logs/architect/issue-1515.md`): Ezri's four `read_page` calls on a ~24,500-character article each returned a summary of its introduction. The AD-1148 loop cap was not involved (`output_truncated: False`, 1,342-2,116 chars).

| # | Defect | Where (live, `4efabdfb`) |
|---|---|---|
| 1 | Tags stripped by regex; the CONTENT of `<style>`/`<script>` is kept and counted as text | `web_agents.py:493-494` (`re.sub(r"<[^>]+>", " ", outcome.body)`) |
| 2 | Cut to the first 8,000 chars | `web_agents.py:496` (`text[:8000]`) |
| 3 | The agent's own cut is never reported; `_with_truncation_notice` only reports the producer's byte cap | `web_agents.py:99-112` (`if not outcome.truncated: return text`) |
| 4 | Caller cannot read more; only `url` is accepted | `agentic_dispatch.py:1838-1848` (schema `{"url"}` only); `_MeshIntentTool.invoke` passes `params` through unchanged (`:1478`) |
| 5 | Same unreported `[:8000]` cut on three sibling sites; the bang branch also counts CSS | `web_agents.py:385` (search results), `:399` (bang page via `_strip_tags`), `:537` (weather JSON) |

`_strip_tags` (`web_agents.py:252-255`) has defect 1 too; it serves DDG titles/snippets (`:285`, `:288`) and the bang landing page (`:399`).

## Decision (Delegated AD Execution Mode: inside the envelope)

No option weakens a security, governance or audit control: every read still goes through `_fetch_or_fail` → `_mesh_fetch_detailed` → mesh `http_fetch` (SSRF guard, rate limits, effect broker classify `read_page` as `network`, `effect_broker.py:344`). The schema change is additive and optional.

### 1. Text extraction — chosen: **A1**

| Rank | Option | Correctness | Safety | Compat | Fit | Reversible | Cost |
|---|---|---|---|---|---|---|---|
| **A1** | stdlib `HTMLParser` subclass in new `probos/utils/html_text.py`; drop content of `script, style, noscript, template, svg`; keep `head` (only `title` survives) and `nav/footer/aside`; `_strip_tags` delegates to it | high | no new dep | `_strip_tags` output equal on ordinary DDG fragments, two measured fixes (`TestStripTagsDelegation`) | `utils` is the dependency-free leaf (22 files import `probos.utils`) | trivial | low |
| A2 | regex pre-pass `<(script|style)...>.*?</\1>` before the old strip | brittle on unclosed/nested/uppercase | — | same | DRY ok | trivial | low |
| A3 | readability/main-content extraction (drop nav/footer/boilerplate) | false positives silently delete article text | needs a dep or a heuristic | — | — | — | high |

Why not drop `nav`/`footer`: they are visible text; some pages carry the table of contents, citations or author there; guessing boilerplate is main-content extraction (A3) whose failure mode is the confident wrong answer this BF removes; with sections, keeping them costs nothing. Why not drop `head`: its only text-bearing child after the skipped elements is `title`, which names the page.

### 2. Reporting the cut — chosen: **B1**

| Rank | Option | Note |
|---|---|---|
| **B1** | Two notices. **Model-facing** `_SECTION_NOTICE` appended after the section text (BF-807 placement), states exact character positions. **Caller-facing** header PREPENDED to the result in `act()` | positions count characters of the very text the model holds, so they are facts (BF-807 refused byte figures because bytes ≠ what the model holds; this is not that case) |
| B2 | Model-facing only | the caller only sees the summary; the model may drop the note; the caller still cannot continue |
| B3 | Append the caller header | AD-869 chat render keeps the first 1,500 chars (`reply_pipeline.py:109`, `:1541-1542`); summaries run 1.3-2.1K, so a trailing header is cut on the `[MESH]` path |

The section notice avoids the phrase `partial document` (BF-807's producer-cap notice, which its tests key on), so the two facts stay distinguishable and can co-occur.

### 3. Reading more — chosen: **C1**

| Rank | Option | AD-1148 cap (live yaml 6,000 = 4,000 head + 2,000 tail, `config/system.yaml:2482-2484`) | LLM passes | Schema | Verdict |
|---|---|---|---|---|---|
| **C1** | optional `offset` (chars into extracted text); each call summarises one 8,000-char section; header gives the next offset | result ≈ 200-char header + ≈2K summary, well under 6,000 | 1 per call (as today) | additive optional property | **chosen**: smallest change, old callers unchanged, matches the MCP reference `fetch` server's `start_index` contract |
| C2 | map-reduce inside one call | small result | k+1 per call, unbounded on a 1 MiB page (≈125 sections) | none | rejected: unbounded spend outside the turn budget (`read_page` is listed as spending outside it, `config/system.yaml:556`), slow (5-7 s per pass) |
| C3 | `mode="text"` returning cleaned raw text | an 8,000-char window is elided mid-text by the 6,000 cap; would need ≤ ~5,500 | 0 | additive | deferred: duplicates `http_fetch` (already returns raw body) and widens raw untrusted text into the crew agent's context |

## The contract (exact)

**`read_page` params:** `url: str` (required, unchanged); `offset: int` optional, default 0, `>= 0`, counted in characters of the extracted text. Accepted forms (`_parse_offset`): absent/`None`/blank string → 0; `int >= 0`; integral `float >= 0`; decimal string of 1-9 ASCII digits (the `[MESH]` tag sends strings). Refused (`None` → failure, **before any fetch and before any model call**): `bool`, negatives, non-integral or NaN floats, `"8,000"`, `"abc"`, `"²"`, 10+ digits, any other type.

**Section size:** `_SECTION_CHARS = 8000` (unchanged figure; now counted after extraction).

**Failure texts** (`IntentResult.success=False`, `error=`; prefix is the existing `_fetch_failure_prefix = "no page was read"`):
- `no page was read: offset must be a whole number of characters, 0 or more`
- `no page was read: the page has no readable text once scripts and styles are removed`
- `no page was read: offset={offset} is at or past the end of the page text ({len} characters)`
- `no page was read: the page could not be read as HTML` (the parser rejected the document: `html_to_text` raised `HtmlTextError`; no model call; logged without the URL, as BF-772 does)

**Extraction contract (`probos.utils.html_text`, review round 1):** `html_to_text` returns text or raises `HtmlTextError` (a `ValueError`), nothing else; there is no degraded mode inside it. Decimal character references are bounded before parsing (`bound_decimal_references`). `read_page` turns `HtmlTextError` into the failure above. `_strip_tags`, which must render search titles and snippets, never raises: on `HtmlTextError` it logs a WARNING and returns `strip_tags_linear(fragment)` (linear passes; drops script and style blocks, recognising their tags by whole name and ending those tags by the HTML attribute rules; other tags are removed by a simple pass; `/>` closes any of the five skipped elements, as XHTML reads it, in this fallback and in `html_to_text` alike; may lose text). `read_page` runs extraction with `await asyncio.to_thread(html_to_text, ...)`.

**Model-facing notice** (appended after section text, only when the section is not the whole text):
`[Note: this is one section of a longer text: characters {start} to {end} of {total}. The text outside that range was left out of this request. Summarise this section only and say that it is one section, not the whole.]`

**Caller-facing header** (prepended as `"{header}\n\n{summary}"`, only on success and only when the section is not the whole text):
- more remains: `[read_page section: characters {start} to {end} of {total} of the page text. More follows: call read_page again with the same url and offset={end} to read the next section.]`
- last section: `[read_page section: characters {start} to {end} of {total} of the page text. This section reaches the end of the page text.]`
- last section of a fetch-capped body (`outcome.truncated`): `[read_page section: characters {start} to {end} of {total} of the text that was retrieved. The source was larger than the fetch limit, so this is the end of what was retrieved and the page itself goes on.]`

**Short page (nonempty whole text ≤ 8,000 chars, read from offset 0) — pinned:** no section notice and no header (a read at an offset inside a short page is a section and gets both: `test_a_short_text_read_from_an_offset_inside_it_is_a_section`, and the reader-level `test_an_offset_at_the_end_is_refused_and_one_before_it_reads`); the caller's result keeps today's shape `{"success": True, "result": <summary>}`. Its model input is the EXTRACTED text (entities decoded, scripts and styles dropped; plus the BF-807 notice only if the producer capped it), not the old regex output: `short &amp; readable` now reaches the model as `short & readable`.

**What a crew agent is told:** the `_MESH_TOOL_SPECS` description and `offset` schema (tool-calling path), and the AD-983a `usage_hint` (rendered into every crew agent's conversational prompt by `_conversational_capability_block`, `cognitive_agent.py:3030-3041`). `IntentDescriptor.params` stays `{"url": "<url>"}` — see Blind spot 1.

All new strings are asserted against the real `_CAPABILITY_GAP_RE` (`decomposer.py:50-57`).

## Prior Art and Blind Spots

- **MCP reference `fetch` server** (`modelcontextprotocol/servers`, `src/fetch/.../server.py`): `start_index` (int, ≥0, default 0) + `max_length`, appends "Content truncated. Call the fetch tool with a start_index of {next_start} to get more content." **Adopted** the shape (offset + stated next offset); **adapted** the placement (header first, because of the 1,500-char chat render) and kept the summarising pass; **rejected** its readability+markdownify extraction (new deps; main-content heuristics, see A3).
- **Internal:** BF-807 notice discipline (`web_agents.py:75-112`, `tests/test_bf807_truncation_reaches_readers.py`); BF-611 lesson (parse before truncating, `web_agents.py:380-383`); BF-772 `_FetchGatedMixin` "fix every caller, not one" (`web_agents.py:158-235`). `docs/research/` has nothing on page reading (Grep `read_page|html to text|start_index` → no files).
- **Blind spot 1 (would have broken a public contract):** the federation MCP server projects every `IntentDescriptor.params` key as **required** (`federation/mcp_server.py:519-526`). Adding `offset` to the descriptor would make it mandatory for an MCP client exposing `read_page`. So `offset` lives only in the tool schema and the usage hint; a test pins the descriptor params unchanged.
- **Blind spot 2:** the BF-807 notice reaches the summarising model, never the caller; the caller only sees `llm_output` (`web_agents.py:235`). A continuation instruction must therefore be added deterministically in `act()`, not left to the model.
- **Blind spot 3:** `[MESH]` tag params are all strings (`dm_sanity_gate.py:308-332`); the offset parser accepts digit strings.
- **Blind spot 4:** extraction can now yield empty text (script-only SPA). That used to reach the model as source code; it now fails honestly rather than calling the model with nothing (the BF-772 fabrication shape).
- **Blind spot 5:** a page that changes between calls shifts offsets. Accepted: every header states the total, so a changed total is visible. Considered, deferred: word-boundary snapping of section ends (more arithmetic and mutation surface for little gain).
- **R-a, speed (corrected in review round 1; the earlier "always faster than the regex it replaces" was wrong):** the extractor grew linearly (1.9-2.1x from 100k to 200k characters) on the 22 shapes measured, no timing test pins this, and slower than the old regex on ordinary markup. Orchestrator, CPython 3.12.13: adjacent table cells at 100k characters, old regex 0.0017 s, new 0.042 s (about 24x slower; the reviewer measured about 14x); seven shapes, including 150k nested `<svg>` closed by `</noscript>` and 4,400-digit references, double from 100k to 200k (ratio 2.0). The old regex was quadratic on runs of `<` (29 s at 200k). Extrapolated: about 0.4 s at the 1 MiB fetch cap. **Ruled (R3): `read_page` extracts with `await asyncio.to_thread(html_to_text, body)`** so that cost does not stall the event loop (pure Python still holds the GIL, so the loop is slowed in 5 ms switch intervals rather than blocked). `html_to_text` is a pure function with its own parser per call, so a worker thread is safe. `_strip_tags` stays synchronous: DDG titles and snippets are short, and the bang landing page is rare. Moving the other readers is considered, deferred.
- **Blind spot 6 (review round 1, F1):** `html.parser` decodes references, in text and in attribute values, with `html.unescape`, which converts decimal digits with `int`; CPython (3.11+ and security backports) refuses more than 4,300 digits, so one zero-padded reference to `A` failed the whole read. Bounded before parsing; the bound is equivalent to `html.unescape` on 406 forms (pinned as one table test). The process-wide limit is NOT raised: that would re-open CPython's quadratic int-parsing guard for every caller.
- **Blind spot 7 (F3):** a counter of skipped depth is not a stack: an unclosed inner `<noscript>` inside a closed `<svg>` lost the rest of the page, and a stray `</noscript>` exposed text inside a `<template>`. Now a stack with per-name counts (amortised O(1) per close tag). Note: `html.parser` treats an unclosed `<style>`/`<script>` as raw text to the end of input, so a later close of an outer element is never seen; unchanged and correct (the rest is hidden, never leaked).
- **Blind spot 8 (F2):** `html.parser` internals are CPython-version dependent (the stdlib has changed its script/comment tokenising in security releases), so no fuzz run proves the failure path unreachable on every interpreter. On CPython 3.12.13, 20,000 fuzzed documents (4,400-digit references in text and attributes, CDATA, declarations, NULs, lone surrogates) raised nothing once references were bounded. Hence an honest-failure path rather than a degraded extraction: any degraded `read_page` text would also shift section offsets between calls. The 4a fixtures pin 3.12 tokenisation; a venv interpreter upgrade reruns them.
- **Blind spot 9:** the linear fallback uses `re.ASCII | re.IGNORECASE`: under plain `IGNORECASE`, `i` also matches U+0130, whose lower case is not a tag name, and `str.lower()` can change a string's length, so offsets taken from a lowered copy would not index the original. It searches the original with per-tag compiled patterns instead.
- **Blind spot 10 (review round 2, M1):** the round-1 fallback closed `<script>` at `</scripture>` and searched for the close from the end of the tag NAME, so a `</script>` inside the start tag's own quoted attribute ended the block (`">HIDDEN_ATTR VISIBLE`; the reviewer forced a rejection and saw `Title: HIDDEN_SCRIPT VISIBLE_TITLE` in a real WebSearchAgent model input). Reachable only after a parser rejection, which no fuzz has produced, but the R1 rule is that no degraded path puts excluded content in front of the model. Fixed by whole-name delimiters and a start-tag scan that follows the WHATWG HTML tokenizer's attribute states (before-attribute-name, attribute-name, before-attribute-value, quoted and unquoted value; `/>` handling per the "self-closing start tag" state and the in-body rule that honours it only for foreign elements such as `svg`) — <https://html.spec.whatwg.org/multipage/parsing.html#tokenization>. Adopted the spec's states, not a tolerant approximation: any approximation that ends a tag EARLIER than the spec can expose content (the "any quote opens" sketch does, Section 1 notes). Linear: a Python loop of anchored matches, each starting where the last ended (pinned structurally by `test_start_tags_are_scanned_forward_only`, not by wall time). Residual, accepted: a comment containing `<script` (`<!-- <script> -->`) hides the rest in the fallback (loss, not leak). (The `/>` part of this ruling is superseded by Blind spot 11.)
- **Blind spot 11 (round-2 recall correction):** XHTML self-closing is honoured on all five skipped elements, unlike a browser reading text/html (which would open the element and hide the rest of the page); a page reader prefers recall; the cost is that code text placed after a self-closed `<script/>` is read as text. Round 2 kept `<script/>`, `<style/>`, `<noscript/>` and `<template/>` open in both extractors, as the WHATWG in-body rules do; executed by the orchestrator, `<head><script type="text/javascript" src="a.js"/></head><body><p>ARTICLE_TEXT</p></body>` read as empty (a "no readable text" failure) and `<p>BEFORE</p><script src="a.js"/><p>AFTER</p>` as `BEFORE`, where the pre-BF-889 regex and round 1 read the article: silent content loss, the failure class this issue removes. An XHTML page (XML, or XHTML served as `application/xhtml+xml`) means an empty element, and `read_page` reads the whole body with no browser in the loop. The opposite risk needs inline code placed after an element its author closed, and the model then sees noise at worst. `html.parser` reports `<x/>` through `handle_startendtag` and enters raw-text mode only from `handle_starttag` (CPython 3.12.13, executed; CPython `main` `Lib/html/parser.py`, read 2026-10-13, keeps that branch), so the stdlib default (start, then end) is the XHTML reading; the fallback matches it. A real unclosed `<script>` still hides the rest in both paths (pinned).
- **Residual R-b (accepted, Low, no code change):** when the fetch was capped (`outcome.truncated`) and a caller asks for an offset past the retrieved text, the refusal says "the end of the page text (N characters)" without the fetch-cap fact; the previous section's header already said the page goes on.
- **Considered, deferred:** RSS description `clean[:200]` and the 10-item cap (`web_agents.py:616-622`) — deliberate digest limits of a headline list, not a document read; unchanged.

## Do not build

- Do not change the AD-1148 loop cap or `tool_result_*` config. Do not change `HttpFetchAgent.MAX_BODY_BYTES`. No HXI change.
- Do not add `offset` to `IntentDescriptor.params` (Blind spot 1).
- Do not add a `mode`, raw-text output, map-reduce summarisation, or boilerplate/nav/footer removal.
- Do not touch fetch security: no change to `_mesh_fetch_detailed`, `http_fetch`, URL guards, rate limits, consensus or the effect broker. `read_page` stays on the governed path.
- Do not add a dependency (no bs4/lxml/trafilatura/readability).
- Do not change `NewsAgent` or `PageReaderAgent.instructions`.
- Do not refactor `WebSearchAgent` beyond the two one-line call-site edits below.

---

## Section 1: new file `src/probos/utils/html_text.py`

Create with exactly this content:

```python
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
```

Notes: this is the code of the scratch file the Architect executed (`logs/architect/scratch_bf889r1/html_text.py`, see Validation). An unclosed `<script>` hides everything after it (data emitted in CDATA mode arrives while `_open` is non-empty). On this venv no input found raises once references are bounded, so the failure tests force it with `monkeypatch` on `_TextCollector.feed` rather than a version-specific input. Method counts for `srp-size`: `_TextCollector` 5 (round 2 added `handle_startendtag`; the round-2 recall correction removes it; the trigger is 15), `HtmlTextError` 0.

Round 2 (2026-10-13): this block is byte-identical to the executed scratch file `logs/architect/scratch_bf889r2/html_text.py`. Rulings: (1) tag names end at an HTML delimiter (`[\t\n\f\r />]` or end of input) in both open and close patterns; (2) a start tag's end is found by `_tag_end`, a Python loop over `_ATTRIBUTE_RE.match` that follows the HTML tokenizer's attribute states (a quote opens a value only after `=`; one in a name or an unquoted value is a character). The orchestrator's sketch (any `"`/`'` opens a quote) was rejected because it leaks: on `<script a" b="x>y</script>">HIDDEN</script> VISIBLE` it pairs the name's `"` with `b="`, ends the tag at `x>`, and returns `">HIDDEN VISIBLE` (pinned; mutant H19 is that sketch, killed); (3) the close tag's end uses the same `_tag_end`; (4) `<script/>`: the fallback follows HTML (`/>` ignored on a non-void HTML element, so content runs to `</script>`; honoured on `svg`, foreign content). `html.parser` alone reports `<script/>` as start-and-end and showed the following text (`html_to_text("a<script/>HIDDEN()</script>b")` was `a HIDDEN() b` on round 1, scratch negative control), so `_TextCollector.handle_startendtag` now keeps the four non-`svg` skipped names open: the same code-to-model leak class, fixed in both extractors, not deferred.

Round-2 recall correction (2026-10-13): ruling (4) is REVERSED (Blind spot 11). It hid the whole article of an XHTML page after `<script src="a.js"/>`. `/>` now closes all five skipped elements in both extractors: `_TextCollector.handle_startendtag` and `_SELF_CLOSING_SKIPPED` are deleted (the stdlib default `handle_startendtag` calls start then end, as in round 1), and `_drop_skipped_linear` tests `if self_closed:`. Rulings (1)-(3), `_tag_end` and the delimiter lookahead are unchanged. The block therefore differs from `logs/architect/scratch_bf889r2/html_text.py` by exactly those three edits plus docstring and comment text; the executed equivalent is that file with `_TextCollector.handle_startendtag` deleted and `_SELF_CLOSING_SKIPPED` set to `SKIPPED_ELEMENTS` (`logs/architect/scratch_bf889r3/`, see Validation).

## Section 2: `src/probos/agents/utility/web_agents.py`

### 2a. Import

SEARCH:
```python
from __future__ import annotations

import html
import json
```
REPLACE:
```python
from __future__ import annotations

import asyncio
import html
import json
```
(`asyncio` is not imported by `web_agents.py` today: its imports are `html, json, logging, re, urllib.parse, xml.etree.ElementTree`, base `:7-16`. It is used once, by `_read_section`, 2f.)

SEARCH:
```python
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)
```
REPLACE:
```python
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)
from probos.utils.html_text import HtmlTextError, html_to_text, strip_tags_linear

logger = logging.getLogger(__name__)
```
(`import html` stays: `_decode_ddg_url` still uses `html.unescape`, `web_agents.py:265`. `import re` stays: DDG regexes and `NewsAgent._parse_rss`.)

### 2b. Section block, inserted between `_with_truncation_notice` and `_mesh_fetch_detailed`

SEARCH:
```python
    return f"{text}\n\n{_TRUNCATION_NOTICE.format(total=total)}"


async def _mesh_fetch_detailed(runtime: Any, url: str) -> FetchOutcome:
```
REPLACE:
```python
    return f"{text}\n\n{_TRUNCATION_NOTICE.format(total=total)}"


#: BF-889: the reader's per-call budget, in characters of EXTRACTED text. The
#: figure is the one the bare ``[:8000]`` slices used; what changed is that it
#: is counted after scripts and styles are dropped, the cut is stated, and the
#: rest of a page is reachable with ``read_page``'s ``offset``.
_SECTION_CHARS = 8000

#: Said to the summarising model when it holds one section of a longer text.
#: The positions are exact: they count characters of the text the model holds,
#: unlike the byte figures BF-807 deliberately refuses to state. Avoids the
#: phrase "partial document", which is BF-807's producer-cap notice, so the two
#: facts stay distinguishable. Checked against `_CAPABILITY_GAP_RE` by tests.
_SECTION_NOTICE = (
    "[Note: this is one section of a longer text: characters {start} to {end} "
    "of {total}. The text outside that range was left out of this request. "
    "Summarise this section only and say that it is one section, not the "
    "whole.]"
)

#: Prepended to the CALLER's result, not the model's input: the summary is
#: model output and may drop the note, and the AD-869 chat render keeps only
#: the first 1,500 characters, so a trailing note could be cut. Plain integers
#: because the caller copies ``offset=`` back verbatim.
_SECTION_HEADER_MORE = (
    "[read_page section: characters {start} to {end} of {total} of the page "
    "text. More follows: call read_page again with the same url and "
    "offset={end} to read the next section.]"
)
_SECTION_HEADER_END = (
    "[read_page section: characters {start} to {end} of {total} of the page "
    "text. This section reaches the end of the page text.]"
)
_SECTION_HEADER_END_FETCH_CUT = (
    "[read_page section: characters {start} to {end} of {total} of the text "
    "that was retrieved. The source was larger than the fetch limit, so this "
    "is the end of what was retrieved and the page itself goes on.]"
)

_OFFSET_RE = re.compile(r"[0-9]{1,9}")


@dataclass(frozen=True)
class TextSection:
    """One bounded section of a longer text (BF-889)."""

    text: str
    start: int
    end: int
    total: int

    @property
    def is_whole(self) -> bool:
        return self.start == 0 and self.end >= self.total

    @property
    def reaches_end(self) -> bool:
        return self.end >= self.total


def _text_section(text: str, offset: int = 0, size: int = _SECTION_CHARS) -> TextSection:
    """``text[offset:offset + size]`` and the positions that describe it.

    ``offset`` is clamped into ``[0, len(text)]``; a caller that must refuse an
    offset past the end checks it before calling.
    """
    total = len(text)
    start = min(max(offset, 0), total)
    end = min(start + size, total)
    return TextSection(text=text[start:end], start=start, end=end, total=total)


def _with_section_notice(section: TextSection) -> str:
    """The section's text, plus :data:`_SECTION_NOTICE` unless it is whole.

    Appended, as BF-807's notice is, so no slice can cut it away.
    """
    if section.is_whole:
        return section.text
    notice = _SECTION_NOTICE.format(
        start=section.start, end=section.end, total=section.total
    )
    return f"{section.text}\n\n{notice}"


def _first_section(text: str) -> str:
    """BF-889: the bounded prefix this module's readers used to take with a
    bare ``[:8000]``, now stated to the model whenever it cuts."""
    return _with_section_notice(_text_section(text))


def _section_header(section: TextSection, outcome: FetchOutcome) -> str:
    """What the caller is told about the section it got; "" for a whole text."""
    if section.is_whole:
        return ""
    fields = {"start": section.start, "end": section.end, "total": section.total}
    if not section.reaches_end:
        return _SECTION_HEADER_MORE.format(**fields)
    if outcome.truncated:
        return _SECTION_HEADER_END_FETCH_CUT.format(**fields)
    return _SECTION_HEADER_END.format(**fields)


def _parse_offset(raw: object) -> int | None:
    """``read_page``'s ``offset``: whole characters into the page text, >= 0.

    Absent or blank means 0. Anything else that is not a whole number of 0 or
    more returns ``None``, which the caller reports instead of reading from 0:
    an agent that asked for section three and got section one would summarise
    the wrong text with confidence. Arrives as an ``int`` from a tool call and
    as a string from the AD-869 ``[MESH read_page url=... offset=8000]`` tag,
    whose params are all strings.
    """
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() and raw >= 0 else None
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return 0
        if _OFFSET_RE.fullmatch(stripped):
            return int(stripped)
    return None


async def _mesh_fetch_detailed(runtime: Any, url: str) -> FetchOutcome:
```

### 2c. `_FetchGatedMixin`: one place sets the failure keys

SEARCH:
```python
            return outcome

        obs["fetch_failed"] = True
        obs["fetch_error"] = f"{self._fetch_failure_prefix}: {reason}"
        logger.warning(
```
REPLACE:
```python
            return outcome

        self._report_fetch_failure(obs, reason)
        logger.warning(
```

SEARCH:
```python
        return None

    async def decide(self, observation: dict) -> dict:
        # Short-circuit before the LLM, as BF-769 does: with no content there is
```
REPLACE:
```python
        return None

    def _report_fetch_failure(self, obs: dict, reason: str) -> None:
        """Mark ``obs`` as a read that produced nothing to reason over.

        ``decide`` then skips the model and ``act`` returns ``success=False``
        with ``"<prefix>: <reason>"``. BF-889 added callers (a bad ``offset``,
        a page with no readable text, an offset past the end), so the two keys
        are set in one place.
        """
        obs["fetch_failed"] = True
        obs["fetch_error"] = f"{self._fetch_failure_prefix}: {reason}"

    async def decide(self, observation: dict) -> dict:
        # Short-circuit before the LLM, as BF-769 does: with no content there is
```

**Revision 2026-10-12 — the caller-facing header travels through the mixin.** BF-772's guard (`tests/test_bf772_fetch_failures_are_honest.py:159-171`) asserts `cls.decide is _FetchGatedMixin.decide` and `cls.act is _FetchGatedMixin.act` for PageReader, Weather and News, because a shadowing `act` once let News return `success=True` after a failed fetch. So `PageReaderAgent` gets no `decide`/`act` of its own (2f); the mixin carries a generic header: observation key → decision key → prepended on the SUCCESS return only. Failure returns are unchanged; an agent that never sets the key (Weather, News) is byte-identical. The two pairs below are against BASE text, do not overlap the two pairs above (base lines 176-177 and 226-235 vs 206-210 and 216-219), and each SEARCH occurs once in base (`_fetch_failure_prefix = "the fetch did not succeed"` once; `"fetch_error": observation.get("fetch_error", "")` once; WebSearchAgent's look-alike pair at `:448-455` uses `search_failed` and is not matched).

SEARCH:
```python
    #: How this agent names what it did not obtain, e.g. "no page was read".
    _fetch_failure_prefix = "the fetch did not succeed"
```
REPLACE:
```python
    #: How this agent names what it did not obtain, e.g. "no page was read".
    _fetch_failure_prefix = "the fetch did not succeed"

    #: BF-889: an observation key a subclass may set in ``perceive``. ``decide``
    #: carries it into the decision and ``act`` puts it ahead of the model's
    #: output on the success return only; failure returns are unchanged. It
    #: lives here, not in a subclass override, because BF-772 requires every
    #: fetch-gated reader to use this ``decide``/``act`` pair. An agent that
    #: never sets the key (Weather, News) gets no header: its success result
    #: is the model's output alone, as before.
    _RESULT_HEADER_KEY = "result_header"
```

SEARCH:
```python
                "fetch_error": observation.get("fetch_error", ""),
            }
        return await super().decide(observation)  # type: ignore[misc]

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        if decision.get("fetch_failed"):
            return {"success": False, "error": decision.get("fetch_error", "")}
        return {"success": True, "result": decision.get("llm_output", "")}
```
REPLACE:
```python
                "fetch_error": observation.get("fetch_error", ""),
            }
        decision = await super().decide(observation)  # type: ignore[misc]
        if header := observation.get(self._RESULT_HEADER_KEY):
            # A copy: the dict returned by CognitiveAgent.decide is left
            # exactly as it was.
            decision = {**decision, self._RESULT_HEADER_KEY: header}
        return decision

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":  # a failed model call: no summary, so no header
            return {"success": False, "error": decision.get("reason")}
        if decision.get("fetch_failed"):
            return {"success": False, "error": decision.get("fetch_error", "")}
        output = decision.get("llm_output", "")
        if header := decision.get(self._RESULT_HEADER_KEY):
            output = f"{header}\n\n{output}"
        return {"success": True, "result": output}
```
(The trailing comment on the `"error"` line is deliberate: it makes that line unique in `web_agents.py` for mutant W17; the same code line without it is at WebSearchAgent `:451`. The copy only leaves the dict `CognitiveAgent.decide` returned unchanged; the cache does not hand out its stored object (hit returns `{**decision, "cached": True}`, `cognitive_agent.py:3650`; miss stores `_cacheable_decision(decision)`, a new dict, `:3762`, `:68-81`).)

### 2d. `_strip_tags` delegates to the shared extractor

SEARCH:
```python
def _strip_tags(fragment: str) -> str:
    """Strip HTML tags and unescape entities from a fragment."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()
```
REPLACE:
```python
def _strip_tags(fragment: str) -> str:
    """Readable text of an HTML fragment or page (BF-889: one extractor).

    Delegates to :func:`probos.utils.html_text.html_to_text`, so a bang
    landing page drops its scripts and styles as ``read_page`` does. On
    ordinary fragments (tags, entities, whitespace) it reads as the old regex
    did; the two measured differences are fixes: a non-breaking space between
    words becomes one space, and a bare ``<`` ... ``>`` span in text is kept,
    not deleted. Pinned by ``TestStripTagsDelegation`` in
    ``tests/test_bf889_read_page_sections.py``.

    Never raises: search titles and snippets must still render. If the
    parser rejects the fragment (no such input is known on CPython 3.12 once
    references are bounded), it falls back, with a warning, to
    :func:`probos.utils.html_text.strip_tags_linear`, which still drops
    script and style blocks.
    """
    try:
        return html_to_text(fragment)
    except HtmlTextError:  # search titles and snippets must still render
        logger.warning(
            "BF-889: html.parser rejected a %d-character fragment; using the "
            "linear tag strip",
            len(fragment),
        )
        return strip_tags_linear(fragment)
```

### 2e. The three sibling `[:8000]` cuts now state themselves

SEARCH:
```python
            obs["fetched_content"] = _with_truncation_notice(
                _format_ddg_results(results)[:8000], outcome
            )
```
REPLACE:
```python
            obs["fetched_content"] = _with_truncation_notice(
                _first_section(_format_ddg_results(results)), outcome
            )
```

SEARCH:
```python
            obs["fetched_content"] = _with_truncation_notice(
                _strip_tags(body)[:8000], outcome
            )
```
REPLACE:
```python
            obs["fetched_content"] = _with_truncation_notice(
                _first_section(_strip_tags(body)), outcome
            )
```

SEARCH:
```python
                obs["fetched_content"] = _with_truncation_notice(
                    outcome.body[:8000], outcome
                )
```
REPLACE:
```python
                obs["fetched_content"] = _with_truncation_notice(
                    _first_section(outcome.body), outcome
                )
```

### 2f. `PageReaderAgent`

SEARCH (from the class line through the end of `perceive`, `web_agents.py:462-498`):
```python
class PageReaderAgent(_FetchGatedMixin, _BundledMixin, CognitiveAgent):
    """Read and summarize a web page (fetched through mesh http_fetch)."""
```
REPLACE:
```python
class PageReaderAgent(_FetchGatedMixin, _BundledMixin, CognitiveAgent):
    """Read and summarize a web page (fetched through mesh http_fetch).

    BF-889: a long page is read in sections of :data:`_SECTION_CHARS`
    characters of extracted text. ``offset`` (optional, default 0) picks the
    section; the caller's result then starts with a header giving the next
    offset. A page whose nonempty text fits in one section, read from offset
    0, gets no header and no section notice, so its result keeps the old
    shape (a read at an offset inside it is a section); the model now reads
    its extracted text (entities decoded, scripts and styles dropped), not
    the old regex output. Extraction runs in a worker thread; a document the
    parser rejects is reported as no page read, never summarised from a
    degraded extraction.
    """
```

SEARCH:
```python
            name="read_page",
            params={"url": "<url>"},
            description="Read and summarize a web page",
            requires_reflect=True,
            usage_hint="[MESH read_page url=<url>] (read & summarize a web page)",
        ),
```
REPLACE:
```python
            name="read_page",
            # BF-889: ``offset`` is deliberately NOT listed here. The federation
            # MCP server marks every descriptor param required
            # (``mcp_server._project_tools_from_descriptors``), so listing it
            # would break an MCP client that exposes read_page. It is taught by
            # ``usage_hint`` (AD-983a) and the agentic tool schema instead.
            params={"url": "<url>"},
            description="Read and summarize a web page",
            requires_reflect=True,
            usage_hint="[MESH read_page url=<url>] (read & summarize a web page; a long page comes in sections: the result gives the next offset, and [MESH read_page url=<url> offset=<n>] reads on)",
        ),
```

SEARCH:
```python
    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        url = obs.get("params", {}).get("url", "")
        if url and self._runtime:
            outcome = await self._fetch_or_fail(obs, url)
            if outcome and outcome.body:
                # Strip HTML tags for cleaner LLM context
                text = re.sub(r"<[^>]+>", " ", outcome.body)
                text = re.sub(r"\s+", " ", text).strip()
                obs["fetched_content"] = _with_truncation_notice(
                    text[:8000], outcome
                )
        return obs
```
REPLACE:
```python
    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        params = obs.get("params", {})
        url = params.get("url", "")
        if url and self._runtime:
            offset = _parse_offset(params.get("offset"))
            if offset is None:
                # Refused before the fetch: no network call for a request that
                # cannot be served.
                self._report_fetch_failure(
                    obs, "offset must be a whole number of characters, 0 or more"
                )
                return obs
            outcome = await self._fetch_or_fail(obs, url)
            if outcome and outcome.body:
                await self._read_section(obs, outcome, offset)
        return obs

    async def _read_section(self, obs: dict, outcome: FetchOutcome, offset: int) -> None:
        """Put the section at ``offset`` into ``obs``, or report why there is none."""
        try:
            # A worker thread: measured 0.2-0.4 s at the 1 MiB fetch cap,
            # which must not stall the event loop. Pure, own parser per call.
            text = await asyncio.to_thread(html_to_text, outcome.body or "")
        except HtmlTextError:  # no text was extracted: say so, do not guess
            logger.warning(
                "BF-889: %s could not extract text from a %d-character page; "
                "reporting failure (the URL is not logged, as in BF-772)",
                type(self).__name__,
                len(outcome.body or ""),
            )
            self._report_fetch_failure(obs, "the page could not be read as HTML")
            return
        if not text:
            # A script-only page used to reach the model as its own source code.
            self._report_fetch_failure(
                obs, "the page has no readable text once scripts and styles are removed"
            )
            return
        if offset >= len(text):
            self._report_fetch_failure(
                obs,
                f"offset={offset} is at or past the end of the page text "
                f"({len(text)} characters)",
            )
            return
        section = _text_section(text, offset)
        obs["fetched_content"] = _with_truncation_notice(
            _with_section_notice(section), outcome
        )
        header = _section_header(section, outcome)
        if header:
            obs[self._RESULT_HEADER_KEY] = header
```

MRO note (verified; revised 2026-10-12): `PageReaderAgent(_FetchGatedMixin, _BundledMixin, CognitiveAgent)`. PageReader defines NO `decide` or `act`: BF-772's guard (`tests/test_bf772_fetch_failures_are_honest.py:159-171`) requires `cls.decide is _FetchGatedMixin.decide` and `cls.act is _FetchGatedMixin.act`. The header reaches the caller through the mixin's `_RESULT_HEADER_KEY` hook (2c): `perceive` sets it, the mixin's `decide` copies it into the decision, the mixin's `act` prepends it on success only. `CognitiveAgent._run_cycle` passes the dict returned by `decide` to `act` (`cognitive_agent.py:7237-7238`, `:7396-7400`); validated end to end through `handle_intent` in scratch.

## Section 3: `src/probos/cognitive/agentic_dispatch.py`

SEARCH:
```python
        "read_page",
        "read_page",
        "Read Page",
        "Fetch and read the contents of a web page by URL.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
```
REPLACE:
```python
        "read_page",
        "read_page",
        "Read Page",
        "Fetch a web page by URL and return a summary of its text. A long page is read in sections of 8,000 characters: the result then starts with a note giving the next offset, and calling read_page again with that offset reads the next section.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Characters into the page's text to start reading "
                        "from. Omit it, or pass 0, for the start; to read on, "
                        "pass the offset given in the previous result's note."
                    ),
                },
            },
            "required": ["url"],
        },
    ),
```
(`"minimum"` precedent for tool schemas: `tools/event_log_query_tool.py:389`, `tools/standing_interest_tool.py:113`.)

### 3b. `tests/test_ad1258_self_knowledge.py`: carve out BF-889's one change to the frozen offer (added 2026-10-12; build in the same milestone as Section 3)

`_BASELINE_OFFER_SHA256` (`:352-354`) is the SHA-256 of the complete ordered offer captured by an independent Windows probe on 2026-09-09; `_assert_baseline_offer` (`:1171-1184`, called at `:1230, :1241, :1311, :1355, :1406`) says never to regenerate it from the offer. Section 3 changes `read_page`'s description and parameters, so 7 tests fail on the digest without this edit (measured by execution on the scratch build).

| Rank | Option | Verdict |
|---|---|---|
| **(a)** | Carve-out: pin the live `read_page` description+parameters to the exact BF-889 values, restore the pre-BF-889 values in a deep copy, hash that against the untouched digest | **chosen.** Oracle digest and its provenance unchanged; the carve-out covers exactly one known transition (any further change to `read_page`, or any change to any other entry or key, still fails) |
| (b) | Derive a new digest and replace the constant | rejected: an independent derivation needs the Windows probe re-run outside this repo; deriving it from the built offer is exactly the "regenerate from this offer" the oracle forbids |
| (c) | Keep the schema; teach `offset` only in the usage hint / result header | rejected (agreed: it loses the tool path): a tool-calling model emits only arguments the schema names, so `offset` would never be sent there; it also undoes C1's tool-path half |

SEARCH:
```python
def _assert_baseline_offer(definitions: list[dict[str, Any]]) -> None:
    """Independent Windows pre-registration capture with historical_offer_inputs."""
    names = [definition["function"]["name"] for definition in definitions]
    assert {"web_search", "read_page", "http_fetch"}.issubset(names)
    assert "run_python" in names
    assert {"search_capabilities", "delegate_task"}.issubset(names)
    assert names == list(_BASELINE_OFFER_NAMES)
    serialized = json.dumps(
        definitions, ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")
```
REPLACE:
```python
# BF-889 (#1515) changed one entry of the offer captured above: read_page gained
# an optional ``offset`` and a description that teaches it. The two pairs below
# are frozen text, not read from the code under test.
_BF889_READ_PAGE_BEFORE: dict[str, Any] = {
    "description": "Fetch and read the contents of a web page by URL.",
    "parameters": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}
_BF889_READ_PAGE_AFTER: dict[str, Any] = {
    "description": (
        "Fetch a web page by URL and return a summary of its text. A long page "
        "is read in sections of 8,000 characters: the result then starts with a "
        "note giving the next offset, and calling read_page again with that "
        "offset reads the next section."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Characters into the page's text to start reading "
                    "from. Omit it, or pass 0, for the start; to read on, "
                    "pass the offset given in the previous result's note."
                ),
            },
        },
        "required": ["url"],
    },
}
_BF889_CARVED_FIELDS = ("description", "parameters")


def _restore_pre_bf889_read_page(
    definitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """A deep copy of ``definitions`` with read_page as it was before BF-889.

    The live read_page entry must equal the BF-889 entry exactly, so the
    carve-out covers one known change and no other: a further change to
    read_page fails here, and a change to any other entry, or to any other key
    of read_page, is left in the copy and fails the digest.
    """
    restored = deepcopy(definitions)
    index = [d["function"]["name"] for d in restored].index("read_page")
    function = restored[index]["function"]
    assert {k: function[k] for k in _BF889_CARVED_FIELDS} == _BF889_READ_PAGE_AFTER, (
        "read_page differs from the BF-889 entry; this carve-out covers that "
        "one change only"
    )
    for key in _BF889_CARVED_FIELDS:
        function[key] = deepcopy(_BF889_READ_PAGE_BEFORE[key])
    others = [d for i, d in enumerate(restored) if i != index]
    assert others == [d for i, d in enumerate(definitions) if i != index]
    live = definitions[index]
    assert {k: v for k, v in restored[index].items() if k != "function"} == {
        k: v for k, v in live.items() if k != "function"
    }
    assert {k: v for k, v in function.items() if k not in _BF889_CARVED_FIELDS} == {
        k: v for k, v in live["function"].items() if k not in _BF889_CARVED_FIELDS
    }
    return restored


def _assert_baseline_offer(definitions: list[dict[str, Any]]) -> None:
    """Independent Windows pre-registration capture with historical_offer_inputs.

    Provenance: ``_BASELINE_OFFER_SHA256`` is the 2026-09-09 independent
    Windows capture and is never regenerated from a live offer. BF-889
    (#1515, 2026-10-12) changed read_page's description and parameters; the
    digest is checked against the offer with that one change restored by
    ``_restore_pre_bf889_read_page``, and the BF-889 entry itself is pinned
    there and in ``tests/test_bf889_read_page_sections.py``.
    """
    names = [definition["function"]["name"] for definition in definitions]
    assert {"web_search", "read_page", "http_fetch"}.issubset(names)
    assert "run_python" in names
    assert {"search_capabilities", "delegate_task"}.issubset(names)
    assert names == list(_BASELINE_OFFER_NAMES)
    serialized = json.dumps(
        _restore_pre_bf889_read_page(definitions),
        ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")
```
Notes for the Builder: `deepcopy`, `json`, `Any` are already imported (`:7`, `:11`, `:15`). Assignment to an existing key keeps its position, so the restored entry serialises in the captured key order. The `:1233-1241` test mutates entry 3 (`run_python`), which the carve-out leaves in the copy, so it still raises with `match="independent Windows"`. The `_BF889_READ_PAGE_AFTER` strings concatenate to exactly the Section 3 text (description: one line in Section 3, four literals here).

## Section 4: tests

### 4a. New file `tests/test_bf889_read_page_sections.py` — exactly this content

```python
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
```

Expected: **114 passed**. Round-2 recall correction: +8 — `TestHtmlToText::test_a_self_closed_script_still_hides_up_to_its_close` (1) replaced by `TestHtmlToText::test_a_self_closed_skipped_element_is_empty_as_in_xhtml` ×4; `TestTheLinearStrip::test_self_closing_ends_an_svg_only` (1) replaced by `TestTheLinearStrip::test_a_self_closed_skipped_element_is_empty_as_in_xhtml` ×4, `test_self_closing_ends_an_svg`, `test_code_after_a_self_closed_script_is_read_as_text`. Before it: **106 passed**. Review round 2: +17 — `test_a_self_closed_script_still_hides_up_to_its_close` (1), `test_a_short_text_read_from_an_offset_inside_it_is_a_section` (1), in `TestTheLinearStrip` 14 (`test_a_close_tag_of_a_longer_name_does_not_close` ×2, `test_a_longer_tag_name_is_not_a_skipped_element`, `test_a_close_tag_or_gt_inside_a_quoted_value_does_not_end_the_tag` ×3, `test_a_quote_opens_a_value_only_after_equals` ×2, `test_a_close_tag_with_whitespace_still_closes`, `test_a_quoted_gt_in_a_close_tag_does_not_end_it`, `test_an_unterminated_quote_hides_the_rest` ×2, `test_self_closing_ends_an_svg_only`, `test_start_tags_are_scanned_forward_only`), `test_the_fallback_hides_script_behind_a_quoted_false_close` (1); the two 4,302-digit attribute tests changed (script/style content added), not counted. Before round 2: **89 passed** (73 as drafted + `test_a_reader_that_sets_no_header_returns_the_summary_alone` + `test_ordinary_fragments_read_as_before_and_two_differences_are_fixes`, revisions 2026-10-12; review round 1: `test_a_parser_failure_degrades_to_tag_stripping` replaced by `test_a_parser_failure_raises_html_text_error`, plus 14 new: `TestCharacterReferences` 4, `TestSkippedElementsNest` 4, `TestTheLinearStrip` 2, `test_strip_tags_falls_back_to_the_linear_strip_with_a_warning`, and in `TestPageReaderReadsInSections` `test_a_parser_failure_fails_the_read_honestly`, `test_a_4302_digit_attribute_reference_reads_through_the_agent`, `test_extraction_runs_off_the_event_loop`).

### 4b. Update `tests/test_utility_agents.py::TestPageReaderAgent::test_perceive_strips_html`

It re-implements the old regex and its docstring calls it "the same approach the agent uses", which is no longer true. **Ruled (R5, review round 1 F4): it now reaches extraction through `perceive`** with a fetched body, using this file's own seam pattern (`agent._runtime = MagicMock()` + `patch.object(web_agents, "_mesh_fetch_detailed", ...)`, as `TestWebSearchAgent` does at `tests/test_utility_agents.py:190-204`), with an inline-CSS premise. The round-0 version called the helper directly, so mutant W19 left it green. Update, do not delete. SEARCH is the whole BASE body (`:243-266`, the imports `MagicMock, patch` are at `:20`):

SEARCH:
```python
        """PageReaderAgent.perceive() strips HTML tags from fetched content.

        We test the stripping logic directly using re.sub (the same approach
        the agent uses). Without a runtime, fetched_content is not set, so
        we verify the observation structure is correct without runtime.
        """
        import re

        raw_html = "<html><body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
        text = re.sub(r"<[^>]+>", " ", raw_html)
        text = re.sub(r"\s+", " ", text).strip()
        assert "<" not in text
        assert "Title" in text
        assert "Hello" in text
        assert "world" in text

        # Agent without runtime still returns valid obs
        agent = _make_agent(PageReaderAgent)
        msg = IntentMessage(intent="read_page", params={"url": "https://example.com"})
        obs = await agent.perceive(msg)
```
REPLACE:
```python
        """PageReaderAgent.perceive() hands on the page's text, not its markup.

        BF-889: this goes through ``perceive`` with a fetched body. It used to
        re-implement the agent's regex inline, so it could not fail when the
        agent's own extraction changed. The inline CSS is the #1515 premise:
        the pre-BF-889 regex kept it. Without a runtime nothing is fetched.
        """
        import re

        from probos.agents.utility import web_agents

        raw_html = (
            "<html><head><style>.nav-item{color:red}</style></head><body>"
            "<h1>Title</h1><p>Hello <b>world</b> &amp; more</p></body></html>"
        )
        # Premise: the regex the agent used before BF-889 keeps the CSS.
        assert ".nav-item" in re.sub(r"<[^>]+>", " ", raw_html)

        async def _fake_fetch(runtime, url):
            return web_agents.FetchOutcome(body=raw_html, status_code=200, final_url=url)

        msg = IntentMessage(intent="read_page", params={"url": "https://example.com"})
        agent = _make_agent(PageReaderAgent)
        agent._runtime = MagicMock()
        with patch.object(web_agents, "_mesh_fetch_detailed", _fake_fetch):
            obs = await agent.perceive(msg)
        assert obs["fetched_content"] == "Title Hello world & more"

        # Agent without runtime still returns valid obs
        agent = _make_agent(PageReaderAgent)
        obs = await agent.perceive(msg)
```
(The three base lines after the SEARCH, `:264-266` — the `obs["params"]["url"]` assert, the `# No fetched_content because runtime is None` comment and the absence assert — stay as they are. Executed in scratch: passes against the revised code; fails under W19.)

---

## Validation already run by the Architect (scratch, not of record)

Under gitignored `logs/architect/scratch_bf889/` with `d:/ProbOS/.venv/Scripts/pytest.exe ... -q -n 0 -p no:randomly`:

| Run | Result |
|---|---|
| `html_text.py` (byte-identical to Section 1) + Section 2b block + `PageReaderAgent` overrides as a subclass (`super(PageReaderAgent, self)` in place of `super()`), injected via a conftest, against the exact 4a test file | **67 passed, 6 failed** |
| The 6 failures | exactly the tests whose sites the scratch could not inject (weather, bang page, DDG block, schema, description, usage hint), each failing on the BF-889 assertion itself, not on setup: **negative controls against unbuilt live code** |
| Mutants on the scratch copies: opening-tag break, closing-tag break, stray-close guard, `match` for `fullmatch`, `[0-9]+` for `{1,9}`, header on failed result | **6/6 killed**; baseline restored to green afterwards |

Not of record for the built files (the reader methods differ in `super` form). The Builder runs the table below once.

**Review round 1 (2026-10-13), scratch `logs/architect/scratch_bf889r1/`** (gitignored): the Section 1 code as `html_text.py`, injected with a `conftest.py` over the staged candidate (worktree `src/` put first on `sys.path`, because the venv's editable install points at `d:/ProbOS/src`); the 2d `_strip_tags` and the 2f `perceive`/`_read_section` assigned onto the module and class (`super(PageReaderAgent, self)`).

| Run | Result |
|---|---|
| The 15 round-1 tests of 4a and the 4b test, copied verbatim with the helpers they use | **16 passed** |
| Same injection, the staged candidate's `tests/test_bf889_read_page_sections.py`, `test_utility_agents.py`, `test_bf772_fetch_failures_are_honest.py`, `test_bf807_truncation_reaches_readers.py` | **203 passed, 1 failed**: the failure is `test_a_parser_failure_degrades_to_tag_stripping`, the round-0 test this revision replaces (the fallback it pinned is removed): **negative control** |
| Mutants H12 (unwind), H13 (count decrement), H16 (unclosed linear element), W25 (no worker thread), W19 (regex extraction) | **5/5 killed** (W19 by the 4b test as well as by `test_a_parser_failure_fails_the_read_honestly` and `test_extraction_runs_off_the_event_loop`); baseline green after each restore |

The orchestrator's own prototype (`logs/architect/proto_html_text.py`, CPython 3.12.13) supplied the fuzz (20,000 documents, nothing raised) and the timing rows (seven shapes, ratio 2.0 from 100k to 200k); the Architect did not rerun them (the bridge allows `pytest.exe`, not `python.exe` scripts).

**Review round 2 (2026-10-13), scratch `logs/architect/scratch_bf889r2/`** (gitignored): `html_text.py` is the Section 1 block (byte equality asserted by `test_prompt_blocks.py::test_section_1_is_the_scratch_file`, which reads this prompt); `conftest.py` loads it as `probos.utils.html_text` before the staged round-1 `web_agents` is imported, so `web_agents` binds the round-2 names (asserted in the conftest). `MODE.txt` = `r1` loads the staged round-1 `src/probos/utils/html_text.py` instead (negative control). All runs `d:/ProbOS/.venv/Scripts/pytest.exe ... -q -n 0 -p no:randomly -p no:cacheprovider`, CPython 3.12.13.

| Run | Result |
|---|---|
| This prompt's 4a block, extracted verbatim to `gen/test_bf889_from_prompt.py`, round-2 injection | **106 passed** |
| Same file against the staged round-1 extractor | **14 failed, 92 passed**: exactly the round-2 additions in `TestHtmlToText` (1), `TestTheLinearStrip` (12) and `TestStripTagsDelegation` (1); the round-1 tests are unaffected |
| L1: the two changed attribute-reference tests with the round-0 behaviour (unbounded `feed` + regex fallback inside `html_to_text`) | **2 failed** (`VISIBLE HIDDEN_SCRIPT() .HIDDEN_STYLE{} after`; `HIDDEN_SCRIPT() .HIDDEN_STYLE{} VISIBLE`): both now discriminate |
| Round-2 injection, the staged `test_bf889_read_page_sections.py` (round-1 content), `test_utility_agents.py`, `test_bf772_fetch_failures_are_honest.py`, `test_bf807_truncation_reaches_readers.py`, plus the 19 scratch round-2 tests | **222 passed** |
| Mutants H17-H24 on the scratch copy | **8/8 killed**; 19/19 green after each restore |

**Round-2 recall correction (2026-10-13), scratch `logs/architect/scratch_bf889r3/test_r3_xhtml.py`** (gitignored; `d:/ProbOS/.venv/Scripts/pytest.exe ... -q -n 0 -p no:randomly -p no:cacheprovider`, CPython 3.12.13). It loads the round-2 scratch `html_text.py` and derives `r3` (`handle_startendtag` deleted, `_SELF_CLOSING_SKIPPED = SKIPPED_ELEMENTS`: behaviourally the Section 1 block), `m22` (r3 with the fallback ignoring `/>` on the four), and `r2` (round 2 as written, whose parser path is mutant H23's). The new 4a assertions were run there as 10 cases per variant (the 4 parser and 4 linear parametrizations, the svg-and-cost case, and an open-`<script>` case).

| Variant | Result |
|---|---|
| r3 | **10/10 passed** (the orchestrator's repro pages read `ARTICLE_TEXT` and `BEFORE AFTER`; `<svg/>` unchanged; an unclosed `<script>` still hides the rest) |
| m22 | **5 failed** (all 4 linear parametrizations, and the cost case `a b`): H22 killed |
| r2 | **9 failed** (4 parser, 4 linear, cost): negative control; its parser path fails all 4 parser parametrizations, so H23 is killed |

Not run: the full revised 4a block against the revised Section 1 block as extracted from this prompt (the evidence above monkeypatches the round-2 file into an equivalent; it does not extract the revised blocks). The Builder's M1 run is the first execution of the block as written.

## Mutation table (Builder: run once after M3; single-line anchors, each occurs exactly once in the named file after the build)

Baseline first: `tests/test_bf889_read_page_sections.py` must be 118 passed, `tests/test_utility_agents.py` 0 failed (W19's second killer lives there), and `tests/test_ad1258_self_knowledge.py` must have 0 failures, else abort. A row whose killer is in the AD-1258 file runs that file. Mutate in place with a `.mutbak` sibling, restore in `finally`. An anchor not found is INERT, not killed.

| ID | File | Anchor (single line) | Replace with | Expected killer |
|---|---|---|---|---|
| H1 | `src/probos/utils/html_text.py` | `            self._open.append(tag)` | `            pass` | `test_style_and_script_content_is_dropped` |
| H2 | same | `        if tag in SKIPPED_ELEMENTS and self._counts.get(tag, 0) > 0:` | `        if tag in SKIPPED_ELEMENTS:` | `test_a_stray_close_tag_does_not_hide_later_text` (the unmatched-end-tag guard: without it the pop hits an empty stack and the read raises `HtmlTextError`) |
| H3 | same | `        if not self._open:` | `        if True:` | `test_style_and_script_content_is_dropped` |
| H4 | same | `    {"script", "style", "noscript", "template", "svg"}` | `    {"script", "noscript", "template", "svg"}` | `test_style_and_script_content_is_dropped` |
| H5 | same | `        self._parts.append(" ")  # word break at an opening tag` | `        pass` | `test_every_opening_and_closing_tag_separates_words` |
| H6 | same | `        self._parts.append(" ")  # word break at a closing tag` | `        pass` | `test_every_opening_and_closing_tag_separates_words` |
| H7 | same | `        raise HtmlTextError(f"html.parser rejected {len(document)} characters") from exc` | `        return ""` | `test_a_parser_failure_raises_html_text_error`, `test_a_parser_failure_fails_the_read_honestly` |
| H8 | same | `        super().__init__(convert_charrefs=True)` | `        super().__init__(convert_charrefs=False)` | `test_entities_are_decoded_exactly_once` |
| H9 | same | `_LEADING_ZEROS_RE = re.compile(r"&#0+(?=[0-9])")` | `_LEADING_ZEROS_RE = re.compile(r"(?!)")` | `test_a_4302_digit_reference_in_text_decodes` |
| H10 | same | `_OUT_OF_RANGE_REF_RE = re.compile(r"&#[1-9][0-9]{7,}")` | `_OUT_OF_RANGE_REF_RE = re.compile(r"(?!)")` | `test_an_overlong_reference_is_the_replacement_character` |
| H11 | same | `        collector.feed(bound_decimal_references(document))` | `        collector.feed(document)` | `test_a_4302_digit_reference_in_text_decodes`, `test_a_4302_digit_attribute_reference_reads_through_the_agent` |
| H12 | same | `                if top == tag:` | `                if True:` | `test_text_after_a_closed_svg_survives_an_unclosed_noscript_inside_it` (stack unwind; killed in scratch) |
| H13 | same | `                self._counts[top] -= 1` | `                pass` | `test_a_close_tag_with_nothing_left_open_is_ignored` (killed in scratch) |
| H14 | same | `    while match := _SKIPPED_OPEN_RE.search(document, pos):` | `    while False:` | `test_it_drops_script_and_style_and_decodes_bounded_references` |
| H15 | same | `    return html.unescape(bound_decimal_references(text)).strip()` | `    return html.unescape(text).strip()` | `test_it_drops_script_and_style_and_decodes_bounded_references` |
| H16 | same | `            return " ".join(kept)  # unclosed: the rest is hidden` | `            return " ".join(kept) + " " + document[match.end():]` | `test_an_unclosed_script_hides_the_rest` (killed in scratch) |
| H17 | same | `_NAME_END = r"(?=[\t\n\f\r />]|\Z)"` | `_NAME_END = r""` | `test_a_close_tag_of_a_longer_name_does_not_close`, `test_a_longer_tag_name_is_not_a_skipped_element` (round 2, killed in scratch) |
| H18 | same | `        content_start, self_closed = _tag_end(document, match.end())` | `        content_start, self_closed = document.find(">", match.end()) + 1 or -1, False` | `test_a_close_tag_or_gt_inside_a_quoted_value_does_not_end_the_tag`, `test_start_tags_are_scanned_forward_only` (round 2, killed in scratch) |
| H19 | same | `    r"(?P<attribute>[^\t\n\f\r />][^\t\n\f\r />=]*"` | `    r"(?P<attribute>\"[^\"]*\"?|'[^']*'?|[^\t\n\f\r />\"'][^\t\n\f\r />=\"']*"` | `test_a_quote_opens_a_value_only_after_equals` (any quote opens a value: the rejected sketch; round 2, killed in scratch) |
| H20 | same | `    r"(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:\"[^\"]*\"?|'[^']*'?|[^\t\n\f\r >]*))?)?"` | `    r"(?:[\t\n\f\r ]*=[\t\n\f\r ]*(?:\"[^\"]*\"|'[^']*'?|[^\t\n\f\r >]*))?)?"` | `test_an_unterminated_quote_hides_the_rest` (round 2, killed in scratch) |
| H21 | same | `            return " ".join(kept)  # the input ends inside the start tag: the rest is hidden` | `            return " ".join(kept) + " " + document[match.end():]` | `test_an_unterminated_quote_hides_the_rest` (round 2, killed in scratch) |
| H22 | same | `        if self_closed:` | `        if False:` | `TestTheLinearStrip::test_a_self_closed_skipped_element_is_empty_as_in_xhtml`, `test_code_after_a_self_closed_script_is_read_as_text`, `test_self_closing_ends_an_svg` (the fallback ignores `/>`; recall correction, equivalent killed in scratch) |
| H23 | same | `        super().__init__(convert_charrefs=True)` | `        super().__init__(convert_charrefs=True); self.handle_startendtag = self.handle_starttag` | `TestHtmlToText::test_a_self_closed_skipped_element_is_empty_as_in_xhtml`, `test_code_after_a_self_closed_script_is_read_as_text` (the parser keeps a self-closed element open; same anchor as H8, applied separately; recall correction, round 2's equivalent parser killed in scratch) |
| H24 | same | `        end, _ = _tag_end(document, close.end())` | `        end, _ = document.find(">", close.end()) + 1 or -1, False` | `test_a_quoted_gt_in_a_close_tag_does_not_end_it` (round 2, killed in scratch) |
| H25 | same | `_NAME_END = r"(?=[\t\n\f\r />]|\Z)"` | `_NAME_END = r"\b"` | `test_a_punctuated_tag_name_is_not_a_skipped_element`, `test_a_close_tag_with_a_punctuated_suffix_does_not_close` (round 3: a word boundary matches before `-`, `.`, `:`; same anchor as H17, applied separately) |
| W1 | `src/probos/agents/utility/web_agents.py` | `        return self.start == 0 and self.end >= self.total` | `        return self.end >= self.total` | `test_a_later_section_is_never_whole_even_at_the_end` |
| W2 | same | `    end = min(start + size, total)` | `    end = start + size` | `test_a_later_section_is_never_whole_even_at_the_end` |
| W3 | same | `        return _SECTION_HEADER_MORE.format(**fields)` | `        return _SECTION_HEADER_END.format(**fields)` | `test_the_header_gives_the_next_offset_while_more_remains` |
| W4 | same | `    if outcome.truncated:` | `    if False:` | `test_the_last_section_of_a_fetch_capped_page_does_not_claim_the_end` |
| W5 | same | `    return f"{section.text}\n\n{notice}"` | `    return section.text` | `test_a_cut_first_section_tells_the_model_after_the_text` |
| W6 | same | `    return _with_section_notice(_text_section(text))` | `    return text[:_SECTION_CHARS]` | `test_weather_states_a_cut_body` |
| W7 | same | `    if isinstance(raw, bool):` | `    if False:` | `test_refused[True]` |
| W8 | same | `        return raw if raw >= 0 else None` | `        return raw` | `test_refused[-1]` |
| W9 | same | `        if _OFFSET_RE.fullmatch(stripped):` | `        if _OFFSET_RE.match(stripped):` | `test_refused[8,000]` |
| W10 | same | `_OFFSET_RE = re.compile(r"[0-9]{1,9}")` | `_OFFSET_RE = re.compile(r"[0-9]+")` | `test_refused[1111111111]` |
| W11 | same | `            if offset is None:` | `            if False:` | `test_a_bad_offset_is_refused_before_any_fetch` |
| W12 | same | `        if not text:` | `        if False:` | `test_a_page_with_no_readable_text_fails_honestly` |
| W13 | same | `        if offset >= len(text):` | `        if offset > len(text):` | `test_an_offset_at_the_end_is_refused_and_one_before_it_reads` |
| W14 | same | `            _with_section_notice(section), outcome` | `            section.text, outcome` | `test_the_cut_reaches_the_summarising_model` |
| W15 | same | `            obs[self._RESULT_HEADER_KEY] = header` | `            pass` | `test_the_caller_gets_the_next_offset_ahead_of_the_summary` |
| W16 | same | `            decision = {**decision, self._RESULT_HEADER_KEY: header}` | `            pass` | `test_the_caller_gets_the_next_offset_ahead_of_the_summary` |
| W17 | same | `        if decision.get("action") == "error":  # a failed model call: no summary, so no header` | `        if False:` | `test_a_failed_model_call_carries_no_section_header` |
| W18 | same | `            output = f"{header}\n\n{output}"` | `            output = f"{output}\n\n{header}"` | `test_the_caller_gets_the_next_offset_ahead_of_the_summary` |
| W24 | same | `        if header := decision.get(self._RESULT_HEADER_KEY):` | `        if (header := decision.get(self._RESULT_HEADER_KEY)) or True:` | `test_a_reader_that_sets_no_header_returns_the_summary_alone` |
| W19 | same | `            text = await asyncio.to_thread(html_to_text, outcome.body or "")` | `            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", outcome.body or "")).strip()` | `test_the_first_read_starts_at_the_article_not_the_css`; also `tests/test_utility_agents.py::TestPageReaderAgent::test_perceive_strips_html` (4b; killed in scratch) |
| W25 | same | the W19 anchor | `            text = html_to_text(outcome.body or "")` | `test_extraction_runs_off_the_event_loop` (killed in scratch) |
| W26 | same | `        except HtmlTextError:  # no text was extracted: say so, do not guess` | `        except ZeroDivisionError:` | `test_a_parser_failure_fails_the_read_honestly` |
| W27 | same | `            self._report_fetch_failure(obs, "the page could not be read as HTML")` | `            pass` | `test_a_parser_failure_fails_the_read_honestly` (the model is then called) |
| W20 | same | `        return html_to_text(fragment)` | `        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()` | `test_a_bang_landing_page_drops_css_and_states_its_cut`, `test_ordinary_fragments_read_as_before_and_two_differences_are_fixes` ("Tom &amp; Jerry" stays undecoded) |
| W28 | same | `    except HtmlTextError:  # search titles and snippets must still render` | `    except ZeroDivisionError:` | `test_strip_tags_falls_back_to_the_linear_strip_with_a_warning` |
| W29 | same | `        return strip_tags_linear(fragment)` | `        return ""` | `test_strip_tags_falls_back_to_the_linear_strip_with_a_warning` |
| W21 | same | `                _first_section(_format_ddg_results(results)), outcome` | `                _format_ddg_results(results)[:8000], outcome` | `test_a_long_search_result_block_states_its_cut` |
| W22 | same | `                _first_section(_strip_tags(body)), outcome` | `                _strip_tags(body)[:8000], outcome` | `test_a_bang_landing_page_drops_css_and_states_its_cut` |
| W23 | same | `                    _first_section(outcome.body), outcome` | `                    outcome.body[:8000], outcome` | `test_weather_states_a_cut_body` |
| U1 | same | `            usage_hint="[MESH read_page url=<url>] (read & summarize a web page; a long page comes in sections: the result gives the next offset, and [MESH read_page url=<url> offset=<n>] reads on)",` | `            usage_hint="[MESH read_page url=<url>] (read & summarize a web page)",` | `test_the_usage_hint_teaches_offset_in_a_tag_that_parses` |
| A1 | `src/probos/cognitive/agentic_dispatch.py` | `        "Fetch a web page by URL and return a summary of its text. A long page is read in sections of 8,000 characters: the result then starts with a note giving the next offset, and calling read_page again with that offset reads the next section.",` | `        "Fetch and read the contents of a web page by URL.",` | `test_the_tool_description_names_sections_and_offset` |
| A2 | same | `                    "minimum": 0,` | `                    "minimum": 1,` | `test_offset_is_an_optional_non_negative_integer` |
| G1 | `src/probos/cognitive/agentic_dispatch.py` | `        "Search the web for information matching a query.",` | `        "Search the web for information matching a query",` | `tests/test_ad1258_self_knowledge.py::test_self_query_offer_historical_inputs_ignore_ambient_platform` (carve-out is tight: another entry's change still fails the digest) |
| G2 | `tests/test_ad1258_self_knowledge.py` | `    "description": "Fetch and read the contents of a web page by URL.",` | `    "description": "Fetch and read the contents of a web page by URL",` | same test (a changed frozen BEFORE string fails the digest) |
| G3 | `src/probos/cognitive/agentic_dispatch.py` | the A1 anchor | the A1 anchor with its final `.` removed | same test (a further change to read_page fails the AFTER pin; the BF-889 file does not kill this one) |

Anchors containing `\n` are the literal two characters backslash-n in source, not newlines (likewise `\t`, `\f`, `\r`, `\Z`, `\"` in H17-H20, H24: raw-string source text). **Round 2:** the `|` characters inside the H17, H19 and H20 anchor and replacement code spans are part of the source line, not table-cell separators; take each row from the raw markdown. Round-2 anchors pre-checked against the scratch file that Section 1 reproduces: each of H17-H24 occurs exactly once in `html_text.py`; H16's anchor (`# unclosed: the rest is hidden`) is not a substring of H21's (`# the input ends inside the start tag: ...`); every round-1 `html_text.py` anchor (H1-H16) is byte-identical and still occurs once (H14's `while match := ...` line and H16's line are unchanged). H17-H24 were each executed in scratch against the 19 round-2 tests: 8/8 killed, baseline green after each restore. Revision anchors pre-checked: `Search the web for information matching a query.` 1 hit in `agentic_dispatch.py`; `Fetch and read the contents` 0 hits in `tests/test_ad1258_self_knowledge.py` before 3b (1 after); `_RESULT_HEADER_KEY`, `header :=`, `output = f"` 0 hits in `web_agents.py` and in this prompt's other blocks; the W17 code line without its comment also occurs at WebSearchAgent `:451`, hence the comment. Total mutants: **60** (review round 3: + H25; 34 drafted, W15-W18 re-anchored, + W24, G1, G2, G3; review round 1: H1, H2, H3, H7, W19, W20 re-anchored, + H9-H16, W25-W29; review round 2: + H17-H24, no anchor changed; round-2 recall correction: H22 and H23 rewritten for the XHTML reading, none added or dropped). **Recall correction:** H22's anchor `        if self_closed:` occurs once in the revised Section 1 block (`_tag_end` returns the flag, it does not test it); H23 reuses H8's anchor line (one line, two separate replacements, like W25/W19) and its replacement is one valid line that shadows the stdlib `handle_startendtag` with `handle_starttag`, so a self-closed element stays open. Round-1 anchors pre-checked by reading the Section 1 and 2d/2f text: each occurs once in its file; the two `except HtmlTextError:` lines differ by indentation AND by their trailing comments, so neither is a substring of the other; `return " ".join(kept)` occurs twice but only once with H16's comment; W25 shares W19's anchor (one line, two replacements). `asyncio`, `HtmlTextError`, `strip_tags_linear` have 0 hits in base `web_agents.py`. Uniqueness pre-checked against live code: `"minimum"` 0 hits in `agentic_dispatch.py`; `if not text`, `TextSection`, `_first_section`, `html_text` 0 hits in `web_agents.py`; `obs["fetch_failed"] = True` 1 hit (`:208`, moved by 2c, still 1 after).

## Milestones (fresh Builder each, about 150 calls)

| M | Scope | Effort | Focused command (all `d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:randomly`) | Exit |
|---|---|---|---|---|
| M0 | Before any edit, on the base tree | 1 call | the M2 file list minus `tests/test_bf889_read_page_sections.py` | record each file's passed/skipped count as BASE; 0 failed expected |
| M1 | Sections 1, 2 (2a-2f) and 4a. The new test file imports Section 2 names, so it cannot collect until 2b and 2f are in | ~70 calls | `tests/test_bf889_read_page_sections.py tests/test_bf807_truncation_reaches_readers.py tests/test_bf772_fetch_failures_are_honest.py tests/test_bf769_blocked_search_fails.py tests/test_utility_agents.py tests/test_ad1258_self_knowledge.py` | new file **116 passed + exactly 2 failed** (`test_offset_is_an_optional_non_negative_integer`, `test_the_tool_description_names_sections_and_offset`: Section 3 pending); every other file equals its BASE count with **0 failed** (BF-772 guard green: PageReader has no own `decide`/`act`; AD-1258 green: the offer is untouched until Section 3) |
| M2 | Section 3 **and 3b together** (3 without 3b turns 7 AD-1258 tests red), then 4b, then the full focused set | ~30 calls | M1 files + `tests/test_ad983a_capability_affordances.py tests/test_ad909_mesh_intent_catalog.py tests/test_ad869_mesh_read_inline.py tests/test_bf629_mesh_synthesis.py tests/test_bf599_yeo_web_research_delegation.py tests/test_ad1147_parallel_tools.py tests/test_ad1148_tool_result_bounds.py` | new file **118 passed, 0 failed**; every other file equals its BASE count with **0 failed** (AD-1258 count unchanged: 3b adds helpers, no tests; `test_utility_agents.py` count unchanged: 4b rewrites one test) |
| M3 | mutation table, checks, trackers, commit locally | ~40 calls | `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` **after `git add`** (both read `git ls-files`; an unstaged new file is invisible) | all **60** mutants killed, files restored, M2 set green again; both checks exit 0 with no baseline change |

Full-suite expectation on the scratch base (orchestrator, not a milestone): the drafted prompt measured 8 failed / 44,408 passed / 60 skipped; under the first revision **0 failed, 44,418 passed, 60 skipped** (the 8 pass, +2 new tests); under review round 1 **0 failed, 44,432 passed, 60 skipped** (+14 net new tests in the BF-889 file; 4b rewrites one test, no count change); under review round 2 **0 failed, 44,449 passed, 60 skipped** (+17 new tests in the BF-889 file; the two attribute-reference tests are changed, not added); under the round-2 recall correction **0 failed, 44,457 passed, 60 skipped** (+8); under review round 3 **0 failed, 44,461 passed, 60 skipped** (+4). Arithmetic from the round-1 figure, not a rerun. The receipted broad gate is the record.

Check expectations: `check_architecture_principles.py` gates `srp-size`, `layer-import` (only substrate/mesh/consensus/cognitive/experience are ranked; `utils` and `agents` are unranked), `db-connect`, `unowned-task`. This change adds no DB access, no task, no ranked-layer import; `PageReaderAgent` gains 1 direct method (`_read_section`; 2 total), `_FetchGatedMixin` gains 1 (`_report_fetch_failure`; 4 total), `_TextCollector` has 5 (drafted-version measurement: srp-size 92, store modules 68; unchanged by the revision, which moves two methods' logic into existing methods). Review round 1 adds no method to any class: `_TextCollector` stays 5 (`__init__`, `handle_starttag`, `handle_endtag`, `handle_data`, `text`), `PageReaderAgent` stays 2 (`perceive`, `_read_section`, now `async`), `_FetchGatedMixin` stays 4; the new class `HtmlTextError` has 0 and the new functions are module-level. Review round 2 added one method, `_TextCollector.handle_startendtag`, and module-level `_tag_end`, `_NAME_END`, `_ATTRIBUTE_RE`, `_SELF_CLOSING_SKIPPED`; the round-2 recall correction removes the method and `_SELF_CLOSING_SKIPPED`, so `_TextCollector` has 5 (trigger 15); no class nears 500 lines. Expect srp-size 92 unchanged; `asyncio.to_thread` is awaited, not a scheduled task, so `unowned-task` is unchanged. Expect exit 0 and no baseline edit. `check_store_registry.py`: no store touched; expect exit 0 unchanged. If either reports a finding, stop and send it to `claude-architect`.

The broad gate is run once by the orchestrator per `.github/copilot-instructions.md` (Testing Standards), not per milestone.

## Tracking

- **`PROGRESS.md`:** add this paragraph at the top, above the AD-1287 S1 paragraph (`PROGRESS.md:3`), followed by a blank line:

```markdown
**BF-889 OPEN (2026-10-12), #1515 -- read_page reads real page text, states its cut, and reads a long page in sections; implementation candidate.** `read_page` stripped tags with a regex that kept the content of `<style>` and `<script>`, cut the result to 8,000 characters without saying so, and accepted only `url` (observed 2026-10-11: four reads of a 24,500-character article each summarised its introduction). A new stdlib extractor, `probos/utils/html_text.py`, drops script, style, noscript, template and svg content, and `_strip_tags` delegates to it. `read_page` takes an optional `offset` (characters into the extracted text); a cut is stated to the summarising model and, ahead of the summary, to the caller with the next offset. The three sibling `[:8000]` cuts in `web_agents.py` now state themselves. A page whose nonempty text fits in 8,000 characters, read from offset 0, gets no section notice and no header and keeps the result shape (a read at an offset inside it is a section and gets both); its model input is the extracted text (entities decoded, scripts and styles dropped), not the old regex output. Character references are bounded before parsing (a 4,302-digit reference no longer fails the read), skipped elements are tracked as a stack, and a document the parser rejects is reported as no page read rather than summarised from a degraded extraction (search snippets fall back to a strip in linear passes that recognises script and style tags by whole name and ends those tags by the HTML attribute rules; other tags are removed by a simple pass); `read_page` extracts in a worker thread (about 0.04 s per 100k characters of ordinary markup, slower than the old regex there, which was quadratic on runs of `<`). `IntentDescriptor.params` is unchanged because the federation MCP server marks every descriptor param required.
```

  Flip to `SHIPPED` with the PR and merge commit at closure (orchestrator).
- **`DECISIONS.md`:** add one entry above `### AD-1287 S1 ...` (`DECISIONS.md:13`):
  `### BF-889 -- read_page reads a long page in sections (2026-10-12, #1515)` followed by 4 lines (line (4), review round 1: *failure contract.* `html_to_text` returns text or raises `HtmlTextError`, with no degraded mode, because `html.parser` internals vary by CPython version and a degraded extraction would hand the model script and style text; `read_page` reports `the page could not be read as HTML`; `_strip_tags` falls back to a linear strip that still drops script and style; references are bounded instead of raising the process-wide int-digit limit; extraction runs in `asyncio.to_thread`; review round 2: the linear strip ends skipped-element tag names at an HTML delimiter and finds those tags' end by the HTML tokenizer's attribute rules (other tags are removed by a simple pass), and `/>` closes all five skipped elements in both extractors, the XHTML reading, because the browser reading hid an XHTML page's whole article after `<script src="a.js"/>`; the accepted cost is that code placed after a self-closed `<script/>` is read as text). Line (1) adds: a page whose nonempty text fits in one section gets no notice or header only when read from offset 0. The first 3 lines: (1) the `offset` contract (optional int >= 0, characters of extracted text, 8,000-character sections, next offset stated in a header prepended to the caller's result); (2) extraction drops script/style/noscript/template/svg only, keeps head/title and nav/footer, stdlib only, in `probos/utils/html_text.py`; (3) `offset` is kept out of `IntentDescriptor.params` because `federation/mcp_server.py` projects every descriptor param as required. Rejected: in-call map-reduce (unbounded spend), raw-text mode (duplicates `http_fetch`; AD-1148 cap would elide an 8,000-char window).
- **`docs/development/roadmap.md`:** no edit. The Bug Tracker carries no BF-870..889 rows (Grep `BF-8[78]\d` → 0 hits); follow current practice.

## Acceptance Criteria

1. `tests/test_bf889_read_page_sections.py`: 118 passed; `TestTheFixtureDiscriminates` passes (the fixture reproduces #1515 under the old extraction).
2. A long page's first read contains the article's opening and no CSS; the model input ends with `_SECTION_NOTICE`; the caller's result starts with the `More follows ... offset=8000` header; following the stated offsets reaches the article's last sentence in `ceil(total/8000)` reads.
3. A short page (nonempty text that fits in one section) read from offset 0: no section notice and no header; read at an offset inside it, it is a section and gets both (`test_a_short_text_read_from_an_offset_inside_it_is_a_section`); model input equals the extracted text (not the old regex output); caller result equals `{"success": True, "result": <summary>}` exactly. No tracker, docstring or test docstring claims a short page reads "exactly as before" beyond that shape.
3a. A 4,302-digit zero-padded reference, in text or in an attribute value, decodes (`A`) and the read succeeds; an out-of-range reference decodes to U+FFFD; the bound agrees with `html.unescape` on the 406-form table; the process-wide int-digit limit is not changed.
3b. Skipped elements nest: the loss, leak, unwind and nothing-open fixtures pass.
3c. A parser rejection: `html_to_text` raises `HtmlTextError` (never a degraded extraction); `read_page` fails with `no page was read: the page could not be read as HTML`, makes no model call and logs no URL; `_strip_tags` returns the linear strip with a WARNING. The linear strip runs in linear passes (no "single/one forward pass" wording anywhere): `</scripture>`/`</stylesheet>` do not close, `<scripts>` is not skipped, `</script >` closes, a close tag or `>` inside a quoted attribute value (either quote style) does not end the start tag, a quote opens a value only after `=`, an unterminated quote hides the rest, and the start-tag scan is forward-only; the `_strip_tags` seam drops script behind a quoted false close. In both `html_to_text` and the linear strip, `/>` closes any of the five skipped elements (XHTML reading, Blind spot 11): a self-closed `<script src="a.js"/>`, `<style/>`, `<noscript/>` or `<template/>` before or inside the body leaves the article readable, `<svg/>` is unchanged, code after a self-closed `<script/>` is read as text, and a real unclosed `<script>` still hides the rest. `_TextCollector` defines no `handle_startendtag` and `_SELF_CLOSING_SKIPPED` does not exist. The two 4,302-digit attribute tests carry script and style content and assert none reaches extracted text or the model input.
3d. `read_page` extraction runs off the event-loop thread (`asyncio.to_thread`); `PageReaderAgent` still defines no `decide`/`act`.
3e. `tests/test_utility_agents.py::TestPageReaderAgent::test_perceive_strips_html` reaches extraction through `perceive` and fails under W19.
4. Bad offsets are refused with no fetch and no model call; an offset at the end is refused; a script-only page fails honestly; every new string is clear of `_CAPABILITY_GAP_RE`.
5. Existing focused files listed in M2 pass with their BASE counts and 0 failures (edited only by 4b and 3b). `PageReaderAgent` defines no `decide`/`act` (BF-772 guard green); `_BASELINE_OFFER_SHA256` is unchanged and AD-1258 is green at every milestone end.
5a. The full suite (receipted broad gate, orchestrator) has **0 failures**.
6. `offset` is optional in the `read_page` tool schema (`required == ["url"]`) and absent from `IntentDescriptor.params`.
7. All 60 mutation-table mutants killed (or any INERT anchor reported, not counted as killed).
8. `check_architecture_principles.py --check` and `check_store_registry.py --check` exit 0 with no baseline change.
9. No change to `_mesh_fetch_detailed`, `http_fetch`, URL guards, rate limits, consensus, the effect broker, the AD-1148 cap or `MAX_BODY_BYTES`.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-10-12, worktree `bf889-1515-20261013-4efabdfb`, HEAD `4efabdfb`)

```
Grep "\[:\d|_with_truncation_notice|_strip_tags|re\.sub" src/probos/agents/utility/web_agents.py
  99:  def _with_truncation_notice(text: str, outcome: FetchOutcome) -> str:
  252: def _strip_tags(fragment: str) -> str:
  254:     text = re.sub(r"<[^>]+>", " ", fragment)
  285:         title = _strip_tags(title_html)
  288:         snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
  384-385:  obs["fetched_content"] = _with_truncation_notice( _format_ddg_results(results)[:8000], outcome
  398-399:  obs["fetched_content"] = _with_truncation_notice( _strip_tags(body)[:8000], outcome
  493: text = re.sub(r"<[^>]+>", " ", outcome.body)
  495-496: obs["fetched_content"] = _with_truncation_notice( text[:8000], outcome
  536-537: obs["fetched_content"] = _with_truncation_notice( outcome.body[:8000], outcome
  616-617: clean = re.sub(r"<[^>]+>", "", desc).strip() / entry += f"\n  {clean[:200]}"
Read web_agents.py:99-112   _with_truncation_notice returns text unchanged unless outcome.truncated
Read web_agents.py:179-216  _fetch_or_fail; :208-209 sets fetch_failed/fetch_error
Read web_agents.py:218-235  _FetchGatedMixin.decide / act (act returns llm_output as result)
Read web_agents.py:462-498  PageReaderAgent (MRO _FetchGatedMixin, _BundledMixin, CognitiveAgent)
Grep "html\.unescape" web_agents.py -> 255, 265  (import html must stay)
Read agentic_dispatch.py:1414-1496  _MeshIntentTool.invoke: IntentMessage(params=dict(params or {})); success -> ToolResult(output=res.result)
Read agentic_dispatch.py:1826-1860  _MESH_TOOL_SPECS read_page entry, schema {"url"} required
Read decomposer.py:50-57  _CAPABILITY_GAP_RE
Read cognitive_agent.py:3009-3076  AD-983a _conversational_capability_block / capability_affordances (renders usage_hint)
Read types.py:957-966  IntentDescriptor.usage_hint (AD-983a)
Read dm_sanity_gate.py:74, 82, 308-354  [MESH ...] regex; params parsed as str key=value
Read reply_pipeline.py:107-109, 1530-1543  read_page synthesised; render cap 1,500, tail cut
Read federation/mcp_server.py:514-534  every desc.params key projected as "required"
Read cognitive_agent.py:3609-3650, 12520-12553  decide cache (default off); fetched_content in cache key
Read cognitive_agent.py:7237-7238, 7396-7400  decide -> decision mutated -> act(decision)
Read config.py:2958-2966  tool_result_max_chars default 0
Grep config/system.yaml tool_result_* -> 2482: 6000, 2483: 4000, 2484: 2000
Read effect_broker.py:344-345  read_page classified effect_class "network"
Read tests/test_bf807_truncation_reaches_readers.py:36-68, 173-358, 502-576  notice pattern; "partial document" keys
Read tests/test_utility_agents.py:243-266  test_perceive_strips_html re-implements the regex
Read tests/test_ad983a_capability_affordances.py:214-232  asserts "[MESH read_page" in hint
Glob src/probos/utils/*.py -> json_extract.py, response_formatter.py, __init__.py, text_sanitize.py
Grep "from probos\.utils" src/probos -> 26 occurrences across 22 files (leaf package)
Read scripts/check_architecture_principles.py:25-133  gated categories; only 5 ranked packages; git ls-files only
WebFetch modelcontextprotocol/servers src/fetch server.py  start_index/max_length contract
pytest (scratch, see "Validation already run"): 67 passed + 6 expected negative controls; 6/6 mutants killed
```

### Revision entries (2026-10-12, same HEAD `4efabdfb`)

```
Orchestrator execution of the drafted prompt (scratch tree bf889-scratch-4efabdfb, derived):
  12/12 SEARCH matched once; new file 73 passed; 34/34 anchors unique; both --check exit 0;
  full suite 8 failed / 44408 passed / 60 skipped -- all 8 caused by the prompt:
Read tests/test_bf772_fetch_failures_are_honest.py:159-171 (per orchestrator; not re-read here)
  test_the_gate_is_not_shadowed_by_an_agents_own_act[PageReaderAgent]: cls.act/decide is _FetchGatedMixin.act/decide
Read tests/test_ad1258_self_knowledge.py:348-354   _BASELINE_OFFER_NAMES; _BASELINE_OFFER_SHA256 = 71ae15e6...f949
Read tests/test_ad1258_self_knowledge.py:1171-1184 _assert_baseline_offer: json.dumps(definitions, ensure_ascii=True, separators=(",",":")) -> sha256
Read tests/test_ad1258_self_knowledge.py:1233-1241 mutates changed[3] (run_python) and expects match="independent Windows"
Grep "_assert_baseline_offer\(" tests/ -> :1171 def; calls :1230, :1241, :1311, :1355, :1406
Grep "^from copy import deepcopy|^import json|^from typing import Any" test_ad1258 -> :11, :7, :15
Read web_agents.py:176-177   _fetch_failure_prefix comment + value (unique; subclasses :484, :526, :576 differ)
Read web_agents.py:218-235   mixin decide/act (pair 4 SEARCH)
Read web_agents.py:442-455   WebSearchAgent decide/act: same "error" lines :451-452, uses search_failed
Grep "result_header" src/probos -> 0
Read cognitive_agent.py:3615-3616  no LLM client -> {"action": "error", "reason": ...}
Read cognitive_agent.py:3629-3650  cache hit returns {**decision, "cached": True} (:3650), a new shallow copy
Read cognitive_agent.py:3760-3764  miss stores _cacheable_decision(decision) (:3762; :68-81 dict comprehension, new dict), returns original
Read cognitive_agent.py:12517-12538  _CACHE_KEY_FIELDS includes params and fetched_content: two sections of one page (different offset/text) never share a key, even with cognitive.decision_cache_enabled on (default off, :12555-12570); header is read from the CURRENT observation after super().decide, so a hit carries the right header. Read from code, not executed.
Read agentic_dispatch.py:1826-1848  web_search description :1831 (1 hit, G1); read_page :1838-1848
```

### Review round 1 entries (2026-10-13, worktree with the round-0 candidate staged)

```
Read logs/architect/review-bf889-a-findings.md  F1-F5 (reviewer, candidate tree f68d7672)
Orchestrator probe (logs/architect/probe_bf889_review_findings.py), CPython 3.12.13, premises asserted -- not rerun here:
  F1 html_to_text("<p>x &#" + "0"*4300 + "65; y</p>") -> ValueError (4,302 digits) from html.unescape in handle_data
     and, for attribute values, parse_starttag; the round-0 fallback called html.unescape again and re-raised
  F2 attribute reference -> fallback text "VISIBLE_BEFORE HIDDEN_script HIDDEN_style VISIBLE_AFTER", reported as success;
     fallback 1.04 s at 50k, 4.67 s at 100k
  F3 "<p>B</p><svg><noscript></svg><p>A</p>" -> "B" (old regex "B A");
     "<template><p>x</p></noscript><p>H</p></template>" -> "H ..."
  F5 adjacent cells at 100k: old regex 0.0017 s, new 0.042 s; old regex 29 s on 200k "<"
Orchestrator prototype (proto_html_text.py + harness), CPython 3.12.13 -- not rerun here:
  bound == html.unescape on 406 forms; 9 stack cases; fuzz 20,000 documents, 0 exceptions; 7 shapes ratio 2.0 (100k->200k)
Grep "^import|^from" src/probos/agents/utility/web_agents.py -> :9 html, :10 json, :11 logging, :12 re, :13 urllib.parse,
  :14 xml.etree.ElementTree, :15 dataclasses, :16 typing; no asyncio (2a adds it)
Grep "asyncio|HtmlTextError|strip_tags_linear" web_agents.py -> 0
Read web_agents.py:346-351  BF-772 warning: "the URL is not logged because a failed fetch can carry a credential"
Read web_agents.py:654-694  staged round-0 perceive/_read_section (2f SEARCH targets are BASE text, unchanged)
Read decomposer.py:50-57  _CAPABILITY_GAP_RE: "could not" is not a branch ("cannot", "unable to" are)
Read tests/test_utility_agents.py:46-48  _make_agent: MockLLMClient, no runtime
Read tests/test_utility_agents.py:190-204  TestWebSearchAgent seam: agent._runtime = MagicMock(); patch.object(web_agents, "_mesh_fetch_detailed", ...)
git diff HEAD -- tests/test_utility_agents.py  base :243-266 body = SEARCH text of 4b (only the docstring/import/text lines changed in round 0)
Grep "_read_section" tests/ -> 0  (making it async breaks no direct caller)
Grep "exactly as before" (PROGRESS.md, DECISIONS.md, src, tests) -> web_agents.py:313 (2c comment, reworded),
  tests/test_bf889_read_page_sections.py:475 (docstring, reworded), PROGRESS.md:3 (Tracking paragraph, reworded);
  DECISIONS.md BF-889 entry (:13-17) has none
Read scripts/check_architecture_principles.py:187-199  SRP_MAX_DIRECT_METHODS = 15; unowned-task counts create_task/ensure_future only
pytest (scratch logs/architect/scratch_bf889r1, -n 0 -p no:randomly): 16 passed; staged files + injection 203 passed,
  1 failed (the replaced round-0 fallback test: negative control); mutants H12, H13, H16, W25, W19(4b) killed
```

### Review round 2 entries (2026-10-13, worktree with the round-1 candidate staged)

```
Grep html_text.py (staged round 1), the defects M1/L2b repaired by Section 1:
  :81   r"<(" + "|".join(sorted(SKIPPED_ELEMENTS)) + r")\b", re.ASCII | re.IGNORECASE   (\b: no HTML delimiter)
  :84   tag: re.compile(f"</{tag}", re.ASCII | re.IGNORECASE) ...                        (prefix close: </scripture>)
  :175  close = _SKIPPED_CLOSE_RES[...].search(document, match.end())                    (searched from the tag NAME end)
  :46, :170, :185  "single forward passes" / "in one forward pass"                        (L2b wording)
Grep web_agents.py (staged): :167-168 is_whole = start == 0 and end >= total (L2a: whole only at offset 0)
                             :434 return strip_tags_linear(fragment)  (the _strip_tags fallback seam)
Grep scripts/check_architecture_principles.py: :188 SRP_MAX_DIRECT_METHODS = 15 (_TextCollector 6 after round 2)
Grep prompt after revision: "forward pass" -> 1 hit, Acceptance 3c's own prohibition; "fits in 8,000"/"fits in one
  section" -> each qualified with "read from offset 0" (Contract, 2f, Tracking PROGRESS, Acceptance 3)
pytest (scratch logs/architect/scratch_bf889r2, see Validation): prompt 4a block 106 passed; round-1 extractor 14 failed;
  Section 1 block == scratch html_text.py (asserted); H17-H24 8/8 killed; L1 round-0 control 2/2 failed
Probe logs/architect/probe_bf889_round2_findings.py (orchestrator) reproduced M1, L2a, L2b on round 1; its M1 shapes are
  the first fixtures of test_a_close_tag_of_a_longer_name_does_not_close / ..._inside_a_quoted_value_...

Round-2 recall correction (2026-10-13):
Read logs/architect/scratch_bf889r2/html_text.py (== round-2 Section 1): handle_startendtag keeps the four open;
  _drop_skipped_linear tests `self_closed and name in _SELF_CLOSING_SKIPPED` (both removed by this revision)
pytest logs/architect/scratch_bf889r3/test_r3_xhtml.py -q -n 0 (CPython 3.12.13): 40 cases, 14 failed / 26 passed =
  r3 10/10 passed; m22 5 failed (H22 killed); r2 9 failed (parser path == H23: killed); m23-by-constant 10/10
  passed (not a mutant of the revised code: the round-2 method read the shared constant; discarded)
  r3 html_to_text("<head><script type=\"text/javascript\" src=\"a.js\"/></head><body><p>ARTICLE_TEXT</p></body>")
     -> "ARTICLE_TEXT"; r2 -> "" (the orchestrator's repro)
  r3 html_to_text("a<script/>CODE()</script>b") -> "a CODE() b" (the accepted cost, pinned)
WebFetch raw.githubusercontent.com/python/cpython/main/Lib/html/parser.py, parse_starttag:
  if end.endswith('/>'): self.handle_startendtag(...) else: self.handle_starttag(...); set_cdata_mode only there
Grep scripts/check_architecture_principles.py: :188 SRP_MAX_DIRECT_METHODS = 15 (_TextCollector 5 after correction)
```

## Absence Verified (2026-10-12)

```
CLAIM: no HTML-to-text helper exists in src
RUN:   Grep "HTMLParser|html\.parser|html_to_text|strip_html|BeautifulSoup|bs4|lxml|trafilatura|html2text|readability" src/
FOUND: cognitive/dependency_resolver.py:20 ("bs4" package-name map), tools/code_execution_tool.py:162 (sandbox package list),
       execution/workspace_result_store.py:264 and swe_harness/tool_call.py:509 (the English word "readability")
HOLDS: yes -- no extractor

CLAIM: the tag-strip regex exists only in web_agents.py
RUN:   Grep "re\.sub\(r["']<\[\^>\]\+>" src/   and   Grep "\"<\[\^>\]|'<\[\^>\]|<script|<style" src/probos --glob *.py
FOUND: web_agents.py:254, 493, 616; the <script> hits are emitted HTML (cloud_pickers.py:210, mcp_servers.py:634, url_route_guard.py:228)
HOLDS: yes

CLAIM: mesh tool params are not schema-validated (an extra optional property cannot be rejected)
RUN:   Grep "jsonschema|validate_tool_params|_validate_params_against_schema" src/probos
FOUND: cognitive/mcp_workbench.py only (MCP tools, not mesh tools)
HOLDS: yes

CLAIM: no test or source pins the old read_page hint or description text
RUN:   Grep "read & summarize a web page|Fetch and read the contents" (repo, excluding logs/)
FOUND: web_agents.py:479, agentic_dispatch.py:1842 (the lines being changed), tests/test_bf599_yeo_web_research_delegation.py:59 (its OWN fixture descriptor)
HOLDS: yes
CORRECTION (2026-10-12): FALSE as a premise. The text search was complete, but the claim was
  "pins", and tests/test_ad1258_self_knowledge.py:352 pins the old description and schema by
  SHA-256 of the whole offer, which no text grep can find. Caught by execution (7 failures).
  Fixed by Section 3b. Lesson: a digest oracle is found by Grep "sha256|hexdigest" on the
  consumers of the changed structure, not by grepping the old text.

CLAIM: no source-text test reads web_agents.py
RUN:   Grep "web_agents(\.py|\b).*(read_text|getsource)|getsource\((web_agents|PageReaderAgent|WebSearchAgent)" tests/   and   Grep "utility[/\\]web_agents|\"web_agents\.py\"" tests/
FOUND: nothing
HOLDS: yes

CLAIM: new anchors are unique (pre-build)
RUN:   Grep "if not text|obs\[\"fetch_failed\"\] = True|_first_section|TextSection|html_text" web_agents.py ; Grep "\"minimum\"" agentic_dispatch.py (count)
FOUND: only web_agents.py:208 (fetch_failed); agentic_dispatch "minimum": 0
HOLDS: yes

CLAIM: docs/research has no prior work on page reading
RUN:   Grep "read_page|html to text|HTML-to-text|start_index" docs/research
FOUND: no files
HOLDS: yes

CLAIM: roadmap Bug Tracker carries no recent BF rows
RUN:   Grep "BF-88\d|BF-87\d" docs/development/roadmap.md
FOUND: nothing
HOLDS: yes -- no roadmap edit
```

Could not run: the built-file mutation campaign and the two `--check` scripts (the bridge allows no source edits by the Architect and only `scripts/ad_ceiling.py` as a Python script); the full suite (orchestrator's broad gate).
