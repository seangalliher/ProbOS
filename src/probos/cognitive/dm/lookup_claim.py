"""AD-1358 S2 (#1750): a 1:1 reply that claims a search or lookup, on a turn whose tool record holds no call.

The write-claim guard (AD-1285, ``write_ledger.py``) checks a claimed save against the turn's record of what was
written. This is the read side. The turn's tool record (AD-1295 ``ToolInvocations``: the names of the calls the
agentic loop made) decides; the reply's wording only selects the turns worth a sentence. So the sentence that
``step_4m_write_claim_guard`` appends is true of every turn it is appended to, whatever the wording matched.

``assess_lookup_claim`` abstains (returns None) unless all of these hold: the record is a ``ToolInvocations`` (None
means the loop did not run or its record could not be read, AD-1269); it lists no call and its ``incomplete`` mark
is exactly False (no call of any pass of the turn was left out for an unverifiable id); the pipeline saw no in-reply
read and dispatched no retry (``record_incomplete`` is exactly False); and ``find_lookup_claim`` finds a claim.

Layer: COGNITIVE and runtime-free: the stdlib and ``probos.dm_reply``. No model call.
"""

from __future__ import annotations

import re

from probos.dm_reply import ToolInvocations

__all__ = ["LOOKUP_DISCLOSURE", "assess_lookup_claim", "find_lookup_claim"]

#: Appended once to the reply. It states a fact of the record, not of the wording, and holds no phrase of
#: ``decomposer._CAPABILITY_GAP_RE`` (a match would misclassify the turn as a capability gap; a test holds it).
LOOKUP_DISCLOSURE = (
    "\n\n[This turn's tool record is empty: no search or lookup was run through a tool on it.]"
)

_MAX_CLAIM_CHARS = 80
_APOS = "['\u2019]"

#: Past-tense claims of a search or record lookup the agent itself made.
_CLAIMS = re.compile(
    r"\bI(?:" + _APOS + r"ve|\s+have)?\s+(?:just\s+|already\s+|also\s+)?"
    r"(?:searched|queried|looked\s+(?:it\s+|that\s+|this\s+|them\s+)?up"
    r"|ran\s+(?:a|another)\s+(?:search|lookup|query)|did\s+(?:a|another)\s+(?:search|lookup)"
    r"|checked\s+(?:the\s+|our\s+|my\s+)?(?:ship" + _APOS + r"s\s+)?"
    r"(?:records?|logs?|archives?|database))\b"
    r"|\b(?:the|my)\s+(?:ship" + _APOS + r"s\s+records\s+|records?\s+)?(?:search|lookup|query)\s+"
    r"(?:turned\s+up|returned|found|came\s+back|shows?|showed)\b"
    r"|\b(?:according\s+to|based\s+on)\s+my\s+(?:search|lookup|query)\b"
    r"|\brecords?\s+I\s+(?:just\s+)?(?:found|pulled|retrieved|looked\s+up)\b",
    re.IGNORECASE,
)
#: Quoted text is not the agent's claim (``_mask_quoted``): a fenced block, only with its closing line (the first
#: later line made only of the same fence character, at least as many, and spaces); paired double quotes, paired
#: curly quotes and backtick spans, each of which may run over line breaks but not over a blank line, so a stray
#: quote reaches no further than its paragraph; and block-quote lines. An unclosed fence makes no fenced span, and a
#: quote with no closer in its paragraph masks nothing; an odd backtick of an unclosed backtick fence's opener can
#: still pair with a later backtick of its paragraph and hide what lies between. A missed mask appends a sentence
#: that is true of the record, a wide one hides it. A line ends in LF or
#: CRLF (the CR directly before the LF belongs to the line break); a lone CR, U+2028, U+2029 or U+0085 is not a
#: line break here.
_FENCE_RUN = re.compile(r"[ \t]*(`{3,}|~{3,})")
_FENCE_ONLY = re.compile(r"[ \t]*(?:`{3,}|~{3,})[ \t]*\r?")
_SPAN_START = re.compile(r'["`\u201c]|^[ \t]*>', re.MULTILINE)
_SPAN_END = {'"': '"', "`": "`", "\u201c": "\u201d"}
#: A line break that starts a blank line (spaces or tabs, then LF or CRLF): no quote or backtick span crosses one.
_PARAGRAPH_BREAK = re.compile(r"\n(?=[ \t]*\r?\n)")


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """The character spans of the fenced blocks that have a closing line, in order.

    Lines are split at LF, so a CRLF line keeps its CR at the end: ``_FENCE_ONLY`` allows it on a closing line,
    and a span ends after that CR.

    Linear in the length of ``text``: a backward pass records, for every line, the longest closing line of each
    fence character after it, so an opener that nothing ends costs one lookup instead of a scan to the end.
    """
    lines = text.split("\n")
    count = len(lines)
    starts: list[int] = []
    runs: list[str] = []
    ending: list[bool] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1
        match = _FENCE_RUN.match(line)
        run = match.group(1) if match else ""
        runs.append(run)
        ending.append(bool(run) and _FENCE_ONLY.fullmatch(line) is not None)
    longest_after = {"`": [0] * count, "~": [0] * count}
    longest = {"`": 0, "~": 0}
    for index in range(count - 1, -1, -1):
        longest_after["`"][index] = longest["`"]
        longest_after["~"][index] = longest["~"]
        if ending[index]:
            char = runs[index][0]
            longest[char] = max(longest[char], len(runs[index]))
    spans: list[tuple[int, int]] = []
    index = 0
    while index < count:
        run = runs[index]
        if not run or longest_after[run[0]][index] < len(run):
            index += 1
            continue
        last = index + 1
        while not (ending[last] and runs[last][0] == run[0] and len(runs[last]) >= len(run)):
            last += 1
        spans.append((starts[index], starts[last] + len(lines[last])))
        index = last + 1
    return spans


def _mask_quoted(text: str) -> str:
    """``text`` with every quoted span blanked to spaces. Every CR and LF is kept, so its length and lines are kept.

    Linear in the length of ``text`` for every input: ``pos`` only moves forward and a found span is skipped
    whole; a failed search for a straight quote or a backtick proves no opener of its kind remains before the
    paragraph break it stopped at; a failed search for a closing curly quote marks the rest of the paragraph, so
    no later curly opener there searches again.
    """
    fences = _fenced_spans(text)
    spans = list(fences)
    breaks = [match.start() for match in _PARAGRAPH_BREAK.finditer(text)]
    next_fence = 0
    next_break = 0
    curly_dead_until = -1
    pos = 0
    while (match := _SPAN_START.search(text, pos)) is not None:
        start = match.start()
        while next_fence < len(fences) and fences[next_fence][1] <= start:
            next_fence += 1
        if next_fence < len(fences) and fences[next_fence][0] <= start:
            pos = fences[next_fence][1]
            continue
        opener = match.group(0)
        if opener.endswith(">"):
            line_end = text.find("\n", start)
            line_end = len(text) if line_end < 0 else line_end
            spans.append((start, line_end))
            pos = line_end
            continue
        while next_break < len(breaks) and breaks[next_break] < start:
            next_break += 1
        limit = breaks[next_break] if next_break < len(breaks) else len(text)
        if opener == "\u201c" and start < curly_dead_until:
            pos = start + 1
            continue
        stop = text.find(_SPAN_END[opener], start + 1, limit)
        if stop < 0:
            if opener == "\u201c":
                curly_dead_until = limit
            pos = start + 1
            continue
        spans.append((start, stop + 1))
        pos = stop + 1
    if not spans:
        return text
    chars = list(text)
    for begin, end in spans:
        for index in range(begin, end):
            if chars[index] not in ("\r", "\n"):
                chars[index] = " "
    return "".join(chars)


#: A word directly before the match that makes it conditional, a question or a negation.
_NOT_A_CLAIM_BEFORE = re.compile(
    r"(?:\b(?:if|whether|unless|have|had|did|not|never)|n" + _APOS + r"t)\s+$", re.IGNORECASE,
)
#: A search of the agent's own memory is recall, not a tool lookup: left to S3.
_MEMORY_AFTER = re.compile(
    r"\s+(?:through\s+|in\s+)?(?:my|our)\s+(?:own\s+)?(?:memor(?:y|ies)|recall|mind)\b", re.IGNORECASE,
)


def find_lookup_claim(text: object) -> str | None:
    """The first search or lookup claim in ``text``'s own wording, at most 80 characters, or None."""
    if type(text) is not str or not text:
        return None
    masked = _mask_quoted(text)
    for match in _CLAIMS.finditer(masked):
        if _NOT_A_CLAIM_BEFORE.search(masked[max(0, match.start() - 16):match.start()]):
            continue
        if _MEMORY_AFTER.match(masked, match.end()):
            continue
        return match.group(0)[:_MAX_CLAIM_CHARS]
    return None


def assess_lookup_claim(text: object, invocations: object, *, record_incomplete: object) -> str | None:
    """The claim to disclose for this turn, or None (abstain). The module docstring lists when it abstains."""
    if record_incomplete is not False:
        return None
    if type(invocations) is not ToolInvocations or invocations.attempted or invocations.succeeded:
        return None
    if invocations.incomplete is not False:
        # A call this record could not list (an unverifiable id) may have been a lookup.
        return None
    return find_lookup_claim(text)
