"""BF-940 (#1686): where the frontmatter of a Markdown document ends.

Ship's Records documents and SKILL.md files open with ``---``, hold YAML, and close with a line of their own. The base cut
each at the first two ``---`` it found, inside a YAML value too, so a value holding ``---`` was cut short and the keys after
it left the frontmatter. This module only frames a document; it loads nothing. Each caller loads the block in its own frame,
so PyYAML's recursion frontier stays where it was (BF-952 A6, L30). It imports nothing of ProbOS (``utils`` holds pure
helpers any layer may import).
"""

from __future__ import annotations

import re

#: A line of three or more hyphens and nothing else but trailing blanks. Group 1 is the hyphens: whatever follows them (the
#: blanks, the line break) belongs to the text after the marker, as what followed the second ``---`` did on the base.
_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$", re.MULTILINE)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Frame ``text`` as ``(block, rest)``: its frontmatter block and the text after it. ``block`` is None with none.

    A text has frontmatter when it begins with ``---``. The block runs from those three hyphens to the first later line
    made only of hyphens (three or more, trailing blanks allowed), line break included; ``rest`` is everything after that
    line's hyphens, not stripped, so a caller that rewrites the document keeps its whitespace. A ``---`` inside a line ends
    nothing. Where no such line follows, the text is framed as the base framed every document: the block ends at the first
    later ``---`` wherever it stands (L18), and ``(None, text)`` returns when there is none.
    """
    if not text.startswith("---"):
        return None, text
    first_break = text.find("\n")
    if first_break != -1:
        closing = _CLOSING_LINE.search(text, first_break + 1)
        if closing is not None:
            return text[3:closing.start()], text[closing.end(1):]
    return base_split_frontmatter(text)  # a text with no closing line is framed as the base framed it (L18)


def base_split_frontmatter(text: str) -> tuple[str | None, str]:
    """Frame ``text`` as the base framed every document: cut at the first two ``---`` it holds, wherever they stand.

    ``block`` is what stands between the opener and the next ``---``, inside a value too, and ``rest`` is what follows it, not
    stripped; ``(None, text)`` for a text that does not begin with ``---`` or holds no later one. It is the rule's answer for a
    text with no closing line (L18), and the cut a reader reads where the rule's block does not load but this one does (A1, F1).
    Wherever ``split_frontmatter`` returns a block this returns one too, and it is that block up to its first ``---`` (U4).
    """
    parts = text.split("---", 2) if text.startswith("---") else []
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, text
