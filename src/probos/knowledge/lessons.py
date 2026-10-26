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

#: The longest section, in characters. Four full sections render to 4,867 characters, so an exit note with its origin
#: line and its Ship's Archive label stays under the 6,000-character tool result cap (AD-1148) and is never elided.
LESSON_SECTION_MAX_CHARS: Final = 1200

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
_SECTION = "(observation|discussion|lesson|recommendation)"
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
_DECLINED = re.compile(r"^\W*no notes\W*$", re.IGNORECASE)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


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

    The four sections must each appear once, in order, each non-empty and at most ``LESSON_SECTION_MAX_CHARS``
    characters. A heading is a markdown heading (``## Observation``), the name alone on its line (``**Observation**``,
    ``Observation``) or a label with a colon (``Observation: text``). Text before the first heading is not part of the
    lesson and is dropped. A ``Cites:`` line belongs to ``parse_citations`` and is never part of a section.
    """
    if type(text) is not str:
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
    if any(not body or len(body) > LESSON_SECTION_MAX_CHARS for body in bodies):
        return None
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
