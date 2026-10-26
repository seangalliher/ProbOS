"""AD-1341 S4 (#1569): the lessons format, and the exit note that carries a lesson across a reset.

A lesson has four sections, in this order, after the naval lessons-learned systems the Captain named (#1569 comment 1):

- Observation: what happened, citing the source episodes;
- Discussion: why it happened and why it mattered;
- Lesson: the general learning;
- Recommendation: what to do differently.

``parse_lesson`` is the one reader. The stand-down (``probos.stand_down``) reads an agent's reply with it, and the
reset's promotion (``probos.knowledge.archive_promotion``) reads the stored note with it, so the archive accepts only
what a stand-down could have written. ``LessonLearned.render`` is the one writer, and a rendered lesson parses back to
itself.

An exit note is the lesson an agent leaves for its successor before a reset: a Ship's Records document at
``exit_note_path(timeline, agent_type)`` whose body is ``exit_note_header`` followed by the rendered lesson, and whose
``exit_note`` frontmatter holds its provenance. It names the agent's own episodes by id; no episode text is copied
into it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

#: The four sections of a lesson, in order.
LESSON_SECTIONS: Final = ("Observation", "Discussion", "Lesson", "Recommendation")

#: The longest a lesson may be: its four sections together, in characters (AD-1341 S4 A2). With the envelope bounds
#: below, a whole archived exit note (the Oracle tool's provenance marker and S2's inheritance label, the
#: ``[exit_note]`` title, the origin line and the four sections) fits one Oracle tool entry (1,200 characters,
#: ``oracle_query_tool._MAX_ENTRY_CHARS``), so a later crew reads the Lesson and the Recommendation, not only the
#: Observation.
LESSON_MAX_CHARS: Final = 700

#: The longest value of each exit-note envelope field (A2). The timeline, callsign and agent type stand in the origin
#: line, and the callsign in the Oracle entry's title, so these bounds are part of the Oracle-entry budget above.
EXIT_NOTE_TIMELINE_MAX_CHARS: Final = 64
EXIT_NOTE_CALLSIGN_MAX_CHARS: Final = 32
EXIT_NOTE_AGENT_TYPE_MAX_CHARS: Final = 48
EXIT_NOTE_DID_MAX_CHARS: Final = 256
EXIT_NOTE_EPISODE_ID_MAX_CHARS: Final = 128

#: The most episodes a lesson cites, and the most a stand-down shows an agent.
LESSON_MAX_CITATIONS: Final = 12

#: The reply that declines. Writing exit notes is optional.
DECLINE_REPLY: Final = "NO NOTES"

#: Where exit notes live in Ship's Records, the frontmatter key that holds their provenance, its version, and the
#: status a stand-down writes them at.
EXIT_NOTES_DIR: Final = "exit-notes"
EXIT_NOTE_KEY: Final = "exit_note"
EXIT_NOTE_VERSION: Final = 1
EXIT_NOTE_STATUS: Final = "submitted"

_NAMES = {name.lower(): name for name in LESSON_SECTIONS}
_SECTION_NAMES = "observation|discussion|lesson|recommendation"
# A4 (R2-F2): the names match in ASCII only. Under re.IGNORECASE alone, U+0130, U+0131 and U+017F match as ASCII
# letters ("Ob\u017fervation"), and _NAMES holds only the ASCII names, so such a heading raised KeyError.
_SECTION = f"((?a:{_SECTION_NAMES}))"
_EMPHASIS = r"(?:\*\*|__)?"
# "## Observation" or "### Observation:": a markdown heading alone on its line.
_HEADING_LINE = re.compile(rf"^\s{{0,3}}#{{1,6}}\s*{_SECTION}\s*:?\s*#*\s*$", re.IGNORECASE)
# "**Observation**" or "Observation": the name alone on its line, bold or plain.
_ALONE_LINE = re.compile(rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*$", re.IGNORECASE)
# "Observation: text", "**Observation:** text", "**Observation**: text". A label needs its colon, so a sentence that
# begins with a section's name ("Lesson learned, ...") stays text.
_LABEL_LINE = re.compile(
    rf"^\s{{0,3}}{_EMPHASIS}\s*{_SECTION}\s*{_EMPHASIS}\s*:\s*{_EMPHASIS}\s*(.*)$", re.IGNORECASE,
)
_CITES_LINE = re.compile(rf"^\s{{0,3}}{_EMPHASIS}\s*cites?\s*{_EMPHASIS}\s*:\s*(.*)$", re.IGNORECASE)
_HANDLE = re.compile(r"\be(\d{1,2})\b", re.IGNORECASE)
_DECLINED = re.compile(r"^[\W_]*no notes[\W_]*$", re.IGNORECASE)  # A2: _ is emphasis too (__NO NOTES__, _NO NOTES_)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")
# A2: what SQLite cannot store whole: a NUL ends its length() and keyword search, and a lone surrogate is no UTF-8.
# A4 (R2-F5): and what a console acts on: the Captain reads exit notes at a terminal, where an ESC sequence redraws it.
# So a lesson holds no C0 or C1 control and no DEL, except tab, line feed and carriage return (which end lines).
_NOT_LESSON_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
# A2: what cannot stand in one line of an exit note: every control character, the line and paragraph separators (each
# ends a line for str.splitlines), and lone surrogates.
_NOT_ONE_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")
# A4 (R2-F3): Ship's Records splits a document's frontmatter at the first two "---" it finds, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one would come back cut short.
_FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True)
class LessonLearned:
    """One lesson in the four-section format. ``parse_lesson`` builds it and enforces the format.

    Not ``Lesson``: ``probos.cognitive.self_improvement`` already exports a ``Lesson`` (``evolution_store.py``), a
    self-improvement outcome with other fields (AD-1341 S4 A1).
    """

    observation: str
    discussion: str
    lesson: str
    recommendation: str

    def render(self) -> str:
        """The lesson as markdown: each section under its ``##`` heading, in order. ``parse_lesson`` reads it back."""
        bodies = (self.observation, self.discussion, self.lesson, self.recommendation)
        return "\n\n".join(f"## {name}\n\n{body}" for name, body in zip(LESSON_SECTIONS, bodies, strict=True))


def _heading(line: str) -> tuple[str, str] | None:
    """The section a line opens and any text after its label, or None when the line opens no section."""
    for pattern in (_HEADING_LINE, _ALONE_LINE):
        match = pattern.match(line)
        if match is not None:
            return _NAMES[match.group(1).lower()], ""
    match = _LABEL_LINE.match(line)
    if match is not None:
        return _NAMES[match.group(1).lower()], match.group(2).strip()
    return None


def parse_lesson(text: object) -> LessonLearned | None:
    """The lesson in ``text``, or None when ``text`` is not in the format (D6).

    The four sections must each appear once, in order, each non-empty, together at most ``LESSON_MAX_CHARS``
    characters. A heading is a markdown heading (``## Observation``), the name alone on its line (``**Observation**``,
    ``Observation``) or a label with a colon (``Observation: text``). Text before the first heading is not part of the
    lesson and is dropped. A ``Cites:`` line belongs to ``parse_citations`` and is never part of a section.

    A2: the format is closed under ``LessonLearned.render``. A section whose text would read as a heading or a
    ``Cites:`` line once rendered on its own line (``Observation: Discussion: ...``) is refused, so every accepted
    lesson is written, stored and read back unchanged. Text SQLite cannot store whole (a NUL, a lone surrogate) is
    refused, and A4 (R2-F5) refuses every other C0 and C1 control and DEL but tab, line feed and carriage return.
    """
    if type(text) is not str or _NOT_LESSON_TEXT.search(text) is not None:
        return None
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        heading = _heading(line)
        if heading is not None:
            name, rest = heading
            sections.append((name, [rest] if rest else []))
        elif _CITES_LINE.match(line):
            continue
        elif sections:
            sections[-1][1].append(line)
    if tuple(name for name, _lines in sections) != LESSON_SECTIONS:
        return None
    bodies = tuple("\n".join(lines).strip() for _name, lines in sections)
    if any(not body for body in bodies) or sum(len(body) for body in bodies) > LESSON_MAX_CHARS:
        return None
    if any(_heading(line) is not None or _CITES_LINE.match(line) for body in bodies for line in body.splitlines()):
        return None  # A2: rendered on its own line, this text would open a section or be read as citations
    return LessonLearned(*bodies)


def is_declined(text: object) -> bool:
    """Whether a reply declines: empty, or ``DECLINE_REPLY`` with nothing around it but punctuation or emphasis."""
    if type(text) is not str:
        return False
    stripped = text.strip()
    return not stripped or _DECLINED.match(stripped) is not None


def parse_citations(text: object, offered: Mapping[str, str]) -> tuple[str, ...]:
    """The episode ids a reply's ``Cites:`` lines name, in order of first mention (D9).

    Only handles in ``offered`` count (``e1`` -> the id of an episode the agent was shown); any other handle is
    dropped. Each id once, at most ``LESSON_MAX_CITATIONS``.
    """
    if type(text) is not str:
        return ()
    cited: list[str] = []
    for line in text.splitlines():
        match = _CITES_LINE.match(line)
        if match is None:
            continue
        for number in _HANDLE.findall(match.group(1)):
            episode_id = offered.get(f"e{int(number)}")
            if episode_id is not None and episode_id not in cited and len(cited) < LESSON_MAX_CITATIONS:
                cited.append(episode_id)
    return tuple(cited)


def _slug(value: object, name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"AD-1341 S4: {name} must be a string")
    slug = _NOT_SLUG.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"AD-1341 S4: {name} has no letter or digit to name a records path with")
    return slug


def exit_notes_directory(timeline_id: str) -> str:
    """The Ship's Records directory that holds one timeline's exit notes."""
    return f"{EXIT_NOTES_DIR}/{_slug(timeline_id, 'timeline_id')}"


def exit_note_path(timeline_id: str, agent_type: str) -> str:
    """The one Ship's Records path of an agent's exit note in a timeline: ``exit-notes/{timeline}/{agent_type}.md``.

    Keyed by agent type, not callsign: a callsign can repeat across generations (AD-1341 S2, RS2-3).
    """
    return f"{exit_notes_directory(timeline_id)}/{_slug(agent_type, 'agent_type')}.md"


def exit_note_header(callsign: str, agent_type: str, timeline_id: str) -> str:
    """An exit note's fixed first line: who left it, for whom, and that it is a record, not a memory (D15)."""
    return (
        f"Exit notes left by {callsign} ({agent_type}) of the crew of timeline {timeline_id} for their successor. "
        "A record, not a memory."
    )


def exit_note_body(callsign: str, agent_type: str, timeline_id: str, lesson: LessonLearned) -> str:
    """An exit note's body: its origin line, then the rendered lesson. Nothing else is written into a note."""
    return f"{exit_note_header(callsign, agent_type, timeline_id)}\n\n{lesson.render()}"


def is_exit_note_text(value: object, max_chars: int) -> bool:
    """A2: whether ``value`` can stand in an exit note's envelope and origin line.

    A string of at most ``max_chars`` characters that is not blank and is one line: no control character, no line or
    paragraph separator, no lone surrogate. SQLite stores the value as UTF-8 and a NUL would end its ``length()`` and
    keyword search; a line break in a callsign would put another heading into the origin line. A4 (R2-F3): and no
    ``---``, which Ship's Records would take for the end of the frontmatter, so the value would come back cut short.
    """
    return (
        type(value) is str and bool(value.strip()) and len(value) <= max_chars and _NOT_ONE_LINE.search(value) is None
        and _FRONTMATTER_DELIMITER not in value  # A4 (R2-F3): Ship's Records cuts a frontmatter value at "---"
    )


def exit_note_provenance_ok(timeline_id: object, callsign: object, agent_type: object, author_did: object) -> bool:
    """A2: whether an exit note's provenance can be written into its envelope and origin line, each within its bound.

    The one check for the stand-down, before it asks an agent, and for the promotion's rule.
    """
    return all(
        is_exit_note_text(value, max_chars)
        for value, max_chars in (
            (timeline_id, EXIT_NOTE_TIMELINE_MAX_CHARS),
            (callsign, EXIT_NOTE_CALLSIGN_MAX_CHARS),
            (agent_type, EXIT_NOTE_AGENT_TYPE_MAX_CHARS),
            (author_did, EXIT_NOTE_DID_MAX_CHARS),
        )
    )


def exit_note_lesson(callsign: str, agent_type: str, timeline_id: str, content: object) -> LessonLearned | None:
    """A2: the lesson of a canonical exit-note body, or None.

    Canonical: ``content`` is exactly ``exit_note_body`` of these fields and the lesson it holds, so the text the
    Captain reviews in Ship's Records is the text the archive receives, and nothing the parser would drop (a preamble,
    a ``Cites:`` line) is ever archived. The stand-down checks its own body with it before writing; the promotion
    withholds a note it refuses.
    """
    lesson = parse_lesson(content)
    if lesson is None or content != exit_note_body(callsign, agent_type, timeline_id, lesson):
        return None
    return lesson
