"""AD-612A: DM regex robustness — tolerant of format variations."""

import re
import pytest

# AD-612: Replicate the two-tier regex from proactive.py for unit testing.
# Tier 1+2 (unified): Closed DMs
_CLOSED_PATTERN = re.compile(
    r'\[DM\s+@?(\S+)\]'
    r'\s*'
    r'((?:(?!\[DM\s).)*?)'
    r'\[/DM\]',
    re.DOTALL | re.IGNORECASE,
)

# Tier 3: Unclosed DMs
_UNCLOSED_PATTERN = re.compile(
    r'\[DM\s+@?(\S+)\]'
    r'\s*'
    r'(.+?)'
    r'(?=\[DM\s|\Z)',
    re.DOTALL | re.IGNORECASE,
)


def _extract(text: str) -> list[tuple[str, str]]:
    """Extract all DMs using the two-tier regex (mirrors proactive.py logic)."""
    results: list[tuple[str, str]] = []
    for m in _CLOSED_PATTERN.finditer(text):
        body = m.group(2).strip()
        results.append((m.group(1), body))
    remaining = _CLOSED_PATTERN.sub('', text)
    for m in _UNCLOSED_PATTERN.finditer(remaining):
        body = m.group(2).strip()
        results.append((m.group(1), body))
    return results


def _clean(text: str) -> str:
    """Strip all DM blocks from text (mirrors proactive.py cleaning)."""
    cleaned = _CLOSED_PATTERN.sub('', text).strip()
    cleaned = _UNCLOSED_PATTERN.sub('', cleaned).strip()
    return cleaned


class TestDmRegexTolerance:
    """AD-612A: DM regex handles format variations."""

    def test_multiline_dm_extracted(self):
        """Original multiline format still works."""
        text = "[DM @Bones]\nMessage body\n[/DM]"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0] == ("Bones", "Message body")

    def test_single_line_dm_extracted(self):
        """Single-line DMs are captured."""
        text = "[DM @Bones] Quick question about crew health [/DM]"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0] == ("Bones", "Quick question about crew health")

    def test_inline_no_space_after_tag(self):
        """No whitespace between tag and body."""
        text = "[DM @Bones]Urgent message[/DM]"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0] == ("Bones", "Urgent message")

    def test_unclosed_dm_extracted(self):
        """Unclosed [DM] tags capture to end of text."""
        text = "[DM @Bones] This message has no closing tag"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0][0] == "Bones"
        assert "no closing tag" in dms[0][1]

    def test_unclosed_dm_before_next_dm(self):
        """Unclosed [DM] captures up to next [DM tag (when clearly separated)."""
        # Two separate DMs: first unclosed, second closed
        text = "Public hello [DM @Bones] first msg\n[DM @Chapel] second msg [/DM]"
        dms = _extract(text)
        assert len(dms) == 2
        callsigns = {d[0] for d in dms}
        assert "Bones" in callsigns
        assert "Chapel" in callsigns
        chapel_dm = [d for d in dms if d[0] == "Chapel"][0]
        assert "second msg" in chapel_dm[1]

    def test_mixed_formats_all_extracted(self):
        """Mix of multiline, single-line, and unclosed — all captured."""
        text = (
            "Public text here.\n"
            "[DM @Atlas]\nMultiline body\n[/DM]\n"
            "[DM @Kira] single line [/DM]\n"
            "[DM @Lynx] unclosed tail"
        )
        dms = _extract(text)
        assert len(dms) == 3
        callsigns = {d[0] for d in dms}
        assert callsigns == {"Atlas", "Kira", "Lynx"}

    def test_case_insensitive(self):
        """[dm @bones] lowercase tags work."""
        text = "[dm @bones] lowercase test [/dm]"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0][0] == "bones"

    def test_empty_body_dm_has_empty_string(self):
        """[DM @Bones][/DM] with empty body extracts as empty string."""
        text = "[DM @Bones][/DM]"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0][1] == ""

    def test_public_text_preserved_after_extraction(self):
        """Non-DM text survives extraction."""
        text = "Hello everyone [DM @Bones] private [/DM] goodbye"
        cleaned = _clean(text)
        assert "Hello everyone" in cleaned
        assert "goodbye" in cleaned
        assert "private" not in cleaned
        assert "[DM" not in cleaned


class TestDmRegexEdgeCases:
    """AD-612A: Edge cases for hardened regex."""

    def test_at_symbol_optional(self):
        """[DM Bones] without @ works."""
        text = "[DM Bones] no at sign [/DM]"
        dms = _extract(text)
        assert len(dms) == 1
        assert dms[0][0] == "Bones"

    def test_multiple_closed_dms_in_one_response(self):
        """Two [DM]...[/DM] blocks both extracted."""
        text = "[DM @Bones] first [/DM] some text [DM @Chapel] second [/DM]"
        dms = _extract(text)
        assert len(dms) == 2

    def test_dm_only_response_returns_empty_public(self):
        """Response that is entirely DM blocks → empty public text."""
        text = "[DM @Bones] message one [/DM]\n[DM @Chapel] message two [/DM]"
        cleaned = _clean(text)
        assert cleaned == ""
