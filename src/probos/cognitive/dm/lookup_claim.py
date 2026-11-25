"""AD-1358 S2 (#1750): a 1:1 reply that claims a search or lookup, on a turn whose tool record holds no call.

The write-claim guard (AD-1285, ``write_ledger.py``) checks a claimed save against the turn's record of what was
written. This is the read side. The turn's tool record (AD-1295 ``ToolInvocations``: the names of the calls the
agentic loop made) decides; the reply's wording only selects the turns worth a sentence. So the sentence that
``step_4m_write_claim_guard`` appends is true of every turn it is appended to, whatever the wording matched.

``assess_lookup_claim`` abstains (returns None) unless all of these hold: the record is a ``ToolInvocations`` (None
means the loop did not run or its record could not be read, AD-1269); it lists no call; the pipeline saw no
in-reply read and adopted no retry (``record_incomplete`` is exactly False); and ``find_lookup_claim`` finds a claim.

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
#: Quoted text is not the agent's claim: double and curly quotes, backticks, block-quote lines.
_QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`|^[ \t]*>.*$', re.MULTILINE)
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
    masked = _QUOTED.sub(lambda m: " " * len(m.group(0)), text)
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
    return find_lookup_claim(text)
