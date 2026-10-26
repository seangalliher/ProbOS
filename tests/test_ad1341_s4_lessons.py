"""AD-1341 S4 M1 (#1569): the lessons format, and an exit note promoted into the Ship's Archive with its provenance.

Real objects throughout: the real parser and renderer; Ship's Records written by the store's own ``write_entry``
(S1's ``_records``, no git); the real promotion service, S3's review and the citation read; the real ``ArchiveStore``
with S3's veto and S1's erasure. ``_write_note`` writes a note as ``probos.stand_down`` writes one, and each of its
keywords breaks one part of the rule; M2's tests write notes through the stand-down itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge.archive_promotion import (
    exit_note_citations,
    plan_promotion,
    promote_ship_records,
    review_promotion,
)
from probos.knowledge.archive_store import PromotionOutcome, SourceKind, VetoOutcome
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_AGENT_TYPE_MAX_CHARS,
    EXIT_NOTE_CALLSIGN_MAX_CHARS,
    EXIT_NOTE_DID_MAX_CHARS,
    EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTE_TIMELINE_MAX_CHARS,
    EXIT_NOTE_VERSION,
    EXIT_NOTES_DIR,
    LESSON_MAX_CHARS,
    LESSON_MAX_CITATIONS,
    LESSON_SECTIONS,
    LessonLearned,
    exit_note_body,
    exit_note_header,
    exit_note_path,
    exit_notes_directory,
    is_declined,
    is_exit_note_text,
    parse_citations,
    parse_lesson,
)
from probos.knowledge.records_store import RecordsStore, _markdown_files_or_raise
from probos.tools.oracle_query_tool import _MAX_ENTRY_CHARS, OracleQueryTool
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _NEXT_SHIP, _SHIP, _config, _data_dir, _records, _reset

_DID = f"did:probos:{_SHIP}:chapel-0001"
_LESSON = LessonLearned(
    observation="The coolant drift alarm fired three times on the night watch before anyone traced it.",
    discussion=(
        "Lesson learned, the hard way: each watch read the alarm as noise because the last had cleared it unlogged."
    ),
    lesson="An alarm cleared without a written cause teaches the next watch to ignore it.",
    recommendation="Log the cause of every cleared alarm, and trace any alarm that repeats a third time.",
)


def _sections() -> tuple[tuple[str, str], ...]:
    bodies = (_LESSON.observation, _LESSON.discussion, _LESSON.lesson, _LESSON.recommendation)
    return tuple(zip(LESSON_SECTIONS, bodies, strict=True))


async def _write_note(
    records: RecordsStore,
    *,
    timeline: str = _SHIP,
    agent_type: str = "surgeon",
    callsign: str = "Chapel",
    did: str = _DID,
    cited: tuple[str, ...] = ("ep-000",),
    envelope: dict[str, Any] | None = None,
    with_envelope: bool = True,
    content: str | None = None,
    path: str | None = None,
    author: str | None = None,
    classification: str = "ship",
    lesson: LessonLearned = _LESSON,
) -> str:
    """An exit note written as ``probos.stand_down`` writes one; each keyword breaks one part of the rule."""
    note_path = path or exit_note_path(timeline, agent_type)
    fields: dict[str, Any] = {
        "version": EXIT_NOTE_VERSION, "timeline_id": timeline, "callsign": callsign, "agent_type": agent_type,
        "author_did": did, "source_episode_ids": list(cited),
    }
    fields.update(envelope or {})
    await records.write_entry(
        author=callsign if author is None else author,
        path=note_path,
        content=exit_note_body(callsign, agent_type, timeline, lesson) if content is None else content,
        message=f"test: exit notes of {callsign}",
        classification=classification,
        status=EXIT_NOTE_STATUS,
        topic=f"Exit notes of {callsign}",
        tags=["exit-notes", "ad-1341"],
        extra_frontmatter={EXIT_NOTE_KEY: fields} if with_envelope else None,
    )
    return note_path


def _deny_reading(monkeypatch: pytest.MonkeyPatch, denied: Path, error: OSError | None = None) -> None:
    """A2: the OS refuses to read ``denied``, as a sharing violation does while an editor or a scanner holds the file.

    Only ``Path.read_text`` of that one file fails, so the real ``RecordsStore.list_entries`` meets the failure inside
    its own loop, on every platform. A5: ``error`` is the failure raised (a sharing violation by default).
    """
    real_read_text = Path.read_text
    target = denied.resolve()

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.resolve() == target:
            if error is not None:
                raise error
            raise PermissionError(13, "the file is being used by another process", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)


@contextlib.contextmanager
def _unreadable(path: Path) -> Iterator[None]:
    """A2: the OS itself refuses to read ``path`` while this is open: a handle that shares nothing on Windows, mode 000
    elsewhere. Skips where this account reads such a file anyway (root on POSIX). A4: ``path`` may be a directory,
    which the OS then refuses to list."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        flags = 0x02000000 if path.is_dir() else 0x80  # A4: FILE_FLAG_BACKUP_SEMANTICS opens a directory
        handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, flags, None)  # GENERIC_READ, share nothing
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel32.CloseHandle(handle)
    else:
        directory, mode = path.is_dir(), path.stat().st_mode
        path.chmod(0)
        try:
            try:
                if directory:
                    os.listdir(path)  # A4: a directory with mode 000 cannot be listed
                else:
                    path.read_text(encoding="utf-8")
            except PermissionError:
                pass
            else:
                pytest.skip("this account reads a file with mode 000 (root): no native read denial to test")
            yield
        finally:
            path.chmod(mode)


def _deny_listing(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """A4 (R2-F1, M3-1): the OS refuses to list the directory ``denied``, as a sharing violation does.

    Only ``os.scandir`` of that one directory fails, so the real traversal inside ``RecordsStore.list_entries`` meets
    the failure itself, on every platform. (Python 3.13's ``glob`` may bind ``scandir`` at import, so the default
    listing's result under this patch is not asserted; the native cases assert it.)
    """
    real_scandir = os.scandir
    target = denied.resolve()

    def scandir(path: Any = ".") -> Any:
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == target:
            raise PermissionError(13, "the directory is being used by another process", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)


def _deny_entry_type(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """A5 (round 3 R3-M1-1): the OS cannot report the type of the entry ``denied`` when its parent is listed
    (``DirEntry.is_dir`` raises), as for a link whose target cannot be examined or a filesystem that reports no
    types. ``os.walk`` filed such an entry as a file and never descended into it. Every listing passes through a
    wrapper; only that one entry's ``is_dir`` fails, and every other attribute is the real entry's."""
    real_scandir = os.scandir
    target = denied.resolve()

    class _Entry:
        def __init__(self, entry: Any) -> None:
            self._entry = entry

        def __getattr__(self, name: str) -> Any:
            return getattr(self._entry, name)

        def is_dir(self, *args: Any, **kwargs: Any) -> bool:
            if Path(self._entry.path).resolve() == target:
                raise PermissionError(13, "the entry's type cannot be read", self._entry.path)
            return bool(self._entry.is_dir(*args, **kwargs))

    class _Listing:
        def __init__(self, listing: Any) -> None:
            self._listing = listing

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *exc: object) -> None:
            self._listing.close()

        def __iter__(self) -> Any:
            return self

        def __next__(self) -> _Entry:
            return _Entry(next(self._listing))

        def close(self) -> None:
            self._listing.close()

    def scandir(path: Any = ".") -> Any:
        return _Listing(real_scandir(path))

    monkeypatch.setattr(os, "scandir", scandir)


def _deny_stat(monkeypatch: pytest.MonkeyPatch, denied: Path, error: OSError) -> None:
    """A5: ``Path.stat`` of ``denied`` fails with ``error``. ``Path.exists`` and ``Path.is_file`` read ENOENT, ENOTDIR,
    EBADF and ELOOP, and three Windows errors ("the device is not ready" among them), as "not there". Compared by
    name, never through ``resolve()``, which calls ``stat`` itself."""
    real_stat = Path.stat
    target = os.path.normcase(os.fspath(denied.resolve()))

    def stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if os.path.normcase(os.fspath(self)) == target:
            raise error
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)


#: A5: the failures 7.3a's table decides, by kind.
_WALK_FAULTS: dict[str, Any] = {
    "absent": lambda where: FileNotFoundError(errno.ENOENT, "gone", where),
    "io": lambda where: OSError(errno.EIO, "I/O error", where),
    "not-a-directory": lambda where: NotADirectoryError(errno.ENOTDIR, "not a directory", where),
    "permission": lambda where: PermissionError(errno.EACCES, "denied", where),
}


class _Trace:
    """A5: the strict walk's filesystem operations in order; with ``fail_at``, that one (1-based) raises ``fault``."""

    def __init__(self, fail_at: int = 0, fault: Any = None) -> None:
        self.operations: list[str] = []
        self.fail_at, self.fault, self.fired = fail_at, fault, ""

    def tick(self, operation: str, where: str) -> None:
        self.operations.append(operation)
        if len(self.operations) == self.fail_at:
            self.fired = operation
            raise self.fault(where)


class _TracedEntry:
    """A5: a directory entry offering only ``name`` and ``is_dir``: 7.3a's table has no row for anything else."""

    def __init__(self, entry: Any, trace: _Trace) -> None:
        self.name: str = entry.name
        self._entry, self._trace = entry, trace

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        assert follow_symlinks is False, "O4 reads the listing record and never follows a link"
        self._trace.tick("is_dir", self._entry.path)
        return bool(self._entry.is_dir(follow_symlinks=False))


class _TracedListing:
    """A5: one traced ``os.scandir`` listing; each step is an operation, the step that ends the listing included."""

    def __init__(self, listing: Any, trace: _Trace, where: str) -> None:
        self._listing, self._trace, self._where = listing, trace, where

    def __enter__(self) -> _TracedListing:
        return self

    def __exit__(self, *exc: object) -> None:
        self._listing.close()

    def __iter__(self) -> _TracedListing:
        return self

    def __next__(self) -> _TracedEntry:
        self._trace.tick("next", self._where)
        return _TracedEntry(next(self._listing), self._trace)


def _traced_walk(root: Path, trace: _Trace) -> list[Path]:
    """A5: the real ``_markdown_files_or_raise`` with every ``os.scandir`` traced, and a tripwire on every other
    filesystem call it could make, so an operation without a row in 7.3a's table fails the test."""
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> _TracedListing:
        where = os.fspath(path)
        trace.tick("open-root" if Path(where) == root else "open-subdirectory", where)
        return _TracedListing(real_scandir(path), trace, where)

    def tripwire(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the strict walk made a filesystem call that 7.3a's table has no row for")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "scandir", scandir)
        for name in ("stat", "lstat", "listdir", "walk"):
            patch.setattr(os, name, tripwire)
        return _markdown_files_or_raise(root)


def _walk_tree(root: Path) -> None:
    """A5: every shape the walk meets: nested directories, two timelines, a directory named ``*.md``, another suffix
    and the suffix in upper case."""
    for relative in (
        "ship-a/surgeon.md", "ship-a/chapel.md", "ship-b/deep/er/nested.md", "ship-b/UPPER.MD", "ship-b/plain.txt",
        "top.md",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("---\nauthor: Bones\n---\n\nA record.\n", encoding="utf-8")
    (root / "folder.md").mkdir()


# --- L1 to L7: the format -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lesson",
    [
        _LESSON,
        LessonLearned("Two lines\nof observation.", "A discussion\n\n  with an indented paragraph.", "One.", "Two."),
    ],
    ids=["one-line", "multi-line"],
)
def test_a_rendered_lesson_parses_back_to_itself(lesson: LessonLearned) -> None:
    rendered = lesson.render()

    assert rendered.startswith("## Observation\n\n")
    assert [line for line in rendered.splitlines() if line.startswith("## ")] == [f"## {n}" for n in LESSON_SECTIONS]
    assert parse_lesson(rendered) == lesson


_FORMS: dict[str, str] = {
    "markdown": _LESSON.render(),
    "markdown-colon": "\n".join(f"### {name}:\n{body}" for name, body in _sections()),
    "bold": "\n".join(f"**{name}**\n{body}" for name, body in _sections()),
    "plain": "\n".join(f"{name}\n{body}" for name, body in _sections()),
    "label": "\n".join(f"{name}: {body}" for name, body in _sections()),
    "bold-label": "\n".join(f"**{name}:** {body}" for name, body in _sections()),
    "preamble-and-cites": f"Here are my notes.\n\n{_LESSON.render()}\nCites: e1, e2\n",
}


@pytest.mark.parametrize("form", sorted(_FORMS))
def test_the_four_sections_are_read_in_each_heading_form(form: str) -> None:
    # _LESSON's discussion opens "Lesson learned, the hard way:": a sentence, never a heading (a label needs its colon).
    assert parse_lesson(_FORMS[form]) == _LESSON


_CLOSURE: dict[str, str] = {
    **_FORMS,
    "label-inline-heading": "Observation: Discussion: the cause\nDiscussion: d\nLesson: l\nRecommendation: r",
    "label-inline-cites": "Observation: Cites: e1\nDiscussion: d\nLesson: l\nRecommendation: r",
    "label-inline-bold-name": "Observation: **Lesson**\nDiscussion: d\nLesson: l\nRecommendation: r",
    "indented-name": "## Observation\n    Discussion\n## Discussion\nd\n## Lesson\nl\n## Recommendation\nr",
}
_REFUSED_FOR_CLOSURE = {"label-inline-heading", "label-inline-cites", "label-inline-bold-name", "indented-name"}


@pytest.mark.parametrize("case", sorted(_CLOSURE))
def test_every_lesson_the_parser_accepts_is_written_and_read_back_unchanged(case: str) -> None:
    """A2 (M1-F3): the format is closed under ``render``. A section that would read as a heading or a ``Cites:`` line
    once rendered on its own line is refused; every accepted lesson renders, and is stored, as text that parses back
    to itself."""
    lesson = parse_lesson(_CLOSURE[case])

    if case in _REFUSED_FOR_CLOSURE:
        assert lesson is None
    else:
        assert lesson is not None
        assert parse_lesson(lesson.render()) == lesson
        assert parse_lesson(exit_note_body("Chapel", "surgeon", _SHIP, lesson)) == lesson


_NOT_LESSONS: dict[str, object] = {
    "missing": "\n\n".join(f"## {name}\n\n{body}" for name, body in _sections()[:3]),
    "reordered": "\n\n".join(f"## {name}\n\n{body}" for name, body in (_sections()[1], _sections()[0], *_sections()[2:])),
    "repeated": f"{_LESSON.render()}\n\n## Lesson\n\nAnd once more.",
    "empty-section": "## Observation\n\n## Discussion\nd\n## Lesson\nl\n## Recommendation\nr",
    "too-long": LessonLearned("o" * (LESSON_MAX_CHARS - 2), "d", "l", "r").render(),  # 701 in all (A2)
    "nul": _LESSON.render().replace("cleared", "clea\x00red"),  # A2: SQLite cannot store it whole
    "surrogate": _LESSON.render() + "\ud800",
    # A4 (R2-F5): what a console acts on; the Captain reads notes at a terminal.
    "escape": _LESSON.render().replace("cleared", "\x1b[2Jcleared"),
    "bell": _LESSON.render().replace("cleared", "\x07cleared"),
    "c1-control": _LESSON.render().replace("cleared", "\x9bcleared"),
    "delete": _LESSON.render().replace("cleared", "\x7fcleared"),
    "vertical-tab": _LESSON.render().replace("night watch", "night\x0bwatch"),
    "prose": "I learned a great deal on this voyage, and I leave it all to my successor.",
    "not-text": 42,
}


@pytest.mark.parametrize("case", sorted(_NOT_LESSONS))
def test_a_reply_not_in_the_format_is_no_lesson(case: str) -> None:
    assert parse_lesson(_NOT_LESSONS[case]) is None


_ASCII_LETTER = re.compile("[a-z]", re.IGNORECASE)


def test_a_section_name_spelled_with_a_lookalike_letter_opens_no_section() -> None:
    """A4 (R2-F2): under Unicode IGNORECASE four letters outside ASCII match as ASCII ones (the dotted capital I, the
    dotless i, the long s, the Kelvin sign), and the section lookup held only ASCII names, so such a heading raised
    ``KeyError`` through the parser, the rule and the plan. The section names now match in ASCII only: every such
    spelling of every section, in every heading form, opens no section, and the reply is refused, never raised."""
    lookalikes = [
        chr(code) for code in range(0x80, 0x110000)
        if not 0xD800 <= code <= 0xDFFF and _ASCII_LETTER.fullmatch(chr(code))
    ]
    assert lookalikes == ["\u0130", "\u0131", "\u017f", "\u212a"]  # premise: Python's documented four
    cases = [
        (name, name[:index] + char + name[index + 1:])
        for name in LESSON_SECTIONS
        for index, letter in enumerate(name.lower())
        for char in lookalikes
        if re.fullmatch(letter, char, re.IGNORECASE)
    ]
    assert len(cases) == 14  # premise: Observation 3, Discussion 7, Lesson 2, Recommendation 2
    for name, variant in cases:
        for heading in (f"## {variant}", f"**{variant}**", variant, f"{variant}: text"):
            assert parse_lesson(_LESSON.render().replace(f"## {name}", heading, 1)) is None, (variant, heading)


def test_a_lesson_carries_no_control_character_but_tab_line_feed_and_carriage_return() -> None:
    """A4 (R2-F5): the Captain reads exit notes at a console, where an escape sequence acts. Every C0 and C1 control
    and DEL is refused anywhere in a reply; tab stays in the text, and line feed and carriage return end lines."""
    for code in (*range(0x00, 0x20), *range(0x7F, 0xA0)):
        lesson = parse_lesson(_LESSON.render().replace("night watch", f"night{chr(code)}watch"))
        if chr(code) in "\t\n\r":
            assert lesson is not None, hex(code)
            assert parse_lesson(lesson.render()) == lesson
        else:
            assert lesson is None, hex(code)


@pytest.mark.parametrize(
    "reply, declined",
    [
        (DECLINE_REPLY, True), ("No notes.", True), ("**NO NOTES**", True), ("", True), ("   \n", True),
        ("__NO NOTES__", True), ("_no notes_", True), ("no_notes", False),
        ("No notes on the coolant yet, but here they are.", False), (_LESSON.render(), False), (None, False),
    ],
    ids=[
        "exact", "punctuation", "bold", "empty", "blank", "underscore-bold", "underscore", "joined-by-underscore",
        "a-sentence", "a-lesson", "not-text",
    ],
)
def test_a_declining_reply_is_recognised_and_nothing_else_is(reply: object, declined: bool) -> None:
    assert is_declined(reply) is declined


_OFFERED = {"e1": "ep-a", "e2": "ep-b", "e3": "ep-c"}


@pytest.mark.parametrize(
    "cites, expected",
    [
        ("Cites: e1, e3", ("ep-a", "ep-c")),
        ("cites: E3 e1 e3", ("ep-c", "ep-a")),
        ("**Cites:** e01", ("ep-a",)),
        ("Cites: e9, e13, x1", ()),
        ("Cites: e2\nCites: e1", ("ep-b", "ep-a")),
        ("", ()),
    ],
    ids=["two", "order-and-once", "bold-and-padded", "not-offered", "two-lines", "none"],
)
def test_citations_name_only_the_episodes_offered(cites: str, expected: tuple[str, ...]) -> None:
    assert parse_citations(f"{_LESSON.render()}\n{cites}", _OFFERED) == expected


def test_a_lesson_cites_at_most_the_bounded_number_of_episodes() -> None:
    offered = {f"e{index}": f"ep-{index:03d}" for index in range(1, 21)}

    cited = parse_citations("Cites: " + ", ".join(offered), offered)

    assert cited == tuple(f"ep-{index:03d}" for index in range(1, LESSON_MAX_CITATIONS + 1))


#: The longest inheritance label S2 writes (a six-digit generation) and the longest provenance marker the Oracle tool
#: puts before an archive entry it has just retrieved (relevance at most 1.00, retrieved under a minute ago).
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:59s]"


async def test_a_whole_note_at_every_bound_reaches_a_later_crew_through_the_oracle_tool(tmp_path: Path) -> None:
    """A2 (M1-F4): the Oracle tool cuts each entry to ``_MAX_ENTRY_CHARS``. A note at every bound (the lesson at
    ``LESSON_MAX_CHARS``, the callsign, agent type and timeline at theirs) reaches a later crew whole: all four
    sections, nothing shortened, with room left for the longest label and marker."""
    names = ("OBS_BODY", "DISCUSSION_BODY", "LESSON_BODY", "RECOMMENDATION_BODY")
    bodies = tuple(f"{name} " + "x" * (LESSON_MAX_CHARS // 4 - len(name) - 1) for name in names)
    assert sum(len(body) for body in bodies) == LESSON_MAX_CHARS  # premise: at the bound
    longest = LessonLearned(*bodies)
    assert parse_lesson(longest.render()) == longest
    assert parse_lesson(LessonLearned(bodies[0] + "x", *bodies[1:]).render()) is None  # one character more
    callsign, agent_type, timeline = (
        "C" * EXIT_NOTE_CALLSIGN_MAX_CHARS, "a" * EXIT_NOTE_AGENT_TYPE_MAX_CHARS, "t" * EXIT_NOTE_TIMELINE_MAX_CHARS,
    )
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, timeline=timeline, agent_type=agent_type, callsign=callsign, lesson=longest)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        assert (await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)).created == (path,)
        oracle = OracleService(archive_store=archive)
        oracle.attach_current_timeline(_NEXT_SHIP)  # a later crew reads it
        result = await OracleQueryTool(oracle=oracle).invoke({"query": "RECOMMENDATION_BODY", "kind": "archive"})
    finally:
        await archive.close()

    assert not result.error and result.metadata["returned_count"] == 1  # premise: the real tool delivered it
    entry = result.output[result.output.index("[source:archive"):].rstrip("\n")
    marker, label = entry.splitlines()[:2]
    assert label.startswith("[Inherited from ")  # premise: S2's label comes first after the marker
    assert "[entry shortened]" not in entry
    for body in bodies:
        assert body in entry  # the Lesson and the Recommendation too, not only the Observation
    worst = len(entry) - len(marker) - len(label) + len(_WORST_MARKER) + len(_WORST_LABEL)
    assert worst <= _MAX_ENTRY_CHARS  # the longest label and marker would still leave it whole


def test_an_exit_note_has_one_path_per_timeline_and_agent_type() -> None:
    assert exit_notes_directory("Ship-DID Alpha/0001") == "exit-notes/ship-did-alpha-0001"
    assert exit_note_path("Ship-DID Alpha/0001", "data_analyst") == "exit-notes/ship-did-alpha-0001/data-analyst.md"
    for bad in ("", "  ", "///", "..", None):
        with pytest.raises(ValueError):
            exit_note_path(bad, "surgeon")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            exit_note_path(_SHIP, bad)  # type: ignore[arg-type]


# --- P1 to P3: the promotion ----------------------------------------------------------------------------------------


async def test_an_exit_note_is_promoted_with_its_own_provenance(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, cited=("ep-000", "ep-001"))
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        promoted = await promote_ship_records(records, archive, timeline_id="timeline-of-the-reset")
    finally:
        await archive.close()

    assert promoted.created == (path,)
    assert promoted.withheld == ()
    columns = (
        "timeline_id, category, title, content, author_agent_type, author_callsign, source_kind, source_ref, "
        "classification, author_did, source_episode_ids"
    )
    assert _rows(tmp_path / "archive.db", f"SELECT {columns} FROM archive") == [(
        _SHIP, "exit_note", "Exit notes of Chapel", exit_note_body("Chapel", "surgeon", _SHIP, _LESSON), "surgeon",
        "Chapel", "exit_note", path, "ship", _DID, json.dumps(["ep-000", "ep-001"]),
    )]


_BROKEN: dict[str, dict[str, Any]] = {
    "no-envelope": {"with_envelope": False},
    "wrong-version": {"envelope": {"version": 2}},
    "blank-did": {"did": "  "},
    "path-mismatch": {"path": "exit-notes/another-timeline/surgeon.md"},
    "author-mismatch": {"author": "Bones"},
    "header-missing": {"content": _LESSON.render()},
    "body-not-in-format": {"content": f"{exit_note_header('Chapel', 'surgeon', _SHIP)}\n\nA few thoughts, unsorted."},
    "too-many-citations": {"cited": tuple(f"ep-{index:03d}" for index in range(LESSON_MAX_CITATIONS + 1))},
    "duplicate-citation": {"cited": ("ep-000", "ep-000")},
    "blank-citation": {"cited": ("ep-000", " ")},
    "department": {"classification": "department"},
    # A2: what the rule checked too little (M1-F2, F5, F6, F7; M2-7).
    "bool-version": {"envelope": {"version": True}},
    "float-version": {"envelope": {"version": 1.0}},
    "newline-callsign": {"callsign": "Chapel\n## Observation"},
    "nul-agent-type": {"agent_type": "sur\x00geon"},
    "surrogate-did": {"did": "did:probos:x:\ud800"},
    "long-callsign": {"callsign": "C" * (EXIT_NOTE_CALLSIGN_MAX_CHARS + 1)},
    "preamble": {
        "content": f"{exit_note_header('Chapel', 'surgeon', _SHIP)}\n\nA preamble the parser drops.\n\n{_LESSON.render()}",
    },
    "standalone-cites": {"content": f"{exit_note_body('Chapel', 'surgeon', _SHIP, _LESSON)}\nCites: e1"},
    # A4: an episode id the rule refuses (R2-F4's missing case), a lookalike heading (R2-F2), a control (R2-F5).
    "long-citation": {"cited": ("ep-000", "e" * (EXIT_NOTE_EPISODE_ID_MAX_CHARS + 1))},
    "newline-citation": {"cited": ("ep-000", "ep\n001")},
    "lookalike-heading": {
        "content": exit_note_body("Chapel", "surgeon", _SHIP, _LESSON).replace("## Lesson", "## Le\u017fson"),
    },
    "control-in-body": {
        "content": exit_note_body("Chapel", "surgeon", _SHIP, _LESSON).replace("cleared", "\x1b[2Jcleared"),
    },
}


@pytest.mark.parametrize("case", sorted(_BROKEN))
async def test_an_exit_note_that_breaks_the_rule_is_withheld_and_stops_nothing(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, **_BROKEN[case])

    plan = await plan_promotion(records, timeline_id=_SHIP)  # never raises: a bad note is withheld

    assert plan.records == ()
    assert plan.withheld == (path,)
    assert await exit_note_citations(records, None) == {}


#: A4 (R2-F3): text YAML must quote or escape, the frontmatter delimiter, and characters outside ASCII.
_YAML_HARD = (
    "---", "--- x", "-- -", "- x", "? x", ": x", "x: y", " #x", "#x", "'x", '"x', "\\x", "{x}", "[x]", "&x", "*x",
    "!x", "%x", "@x", "`x", "|x", ">x", "~", "null", "yes", "No", "1", "1.0", "0x1F", "2026-10-26", " x", "x ",
    "x  y", "...", "\u00e9", "\U0001f680", "\ufeff", "\u00a0", "\u0085", "\u2028",
)


@pytest.mark.parametrize("field", ["callsign", "agent_type", "did", "cited"])
async def test_every_provenance_value_the_rule_admits_comes_back_whole_from_ship_s_records(
    tmp_path: Path, field: str,
) -> None:
    """A4 (R2-F3): Ship's Records cuts a document's frontmatter at the first two ``---`` it finds, wherever they stand
    (register R25), so a callsign such as ``normal---value`` came back as ``normal``: the stand-down reported the
    note written and the promotion withheld it. The rule now refuses a value holding ``---``. Each value here (YAML's
    quoting cases, and for the callsign, which the store writes three times, every code point to U+017F) is either
    refused by the rule and withheld, or admitted, stored, read back whole and archived."""
    records = _records(_data_dir(tmp_path))
    bound = {
        "callsign": EXIT_NOTE_CALLSIGN_MAX_CHARS, "agent_type": EXIT_NOTE_AGENT_TYPE_MAX_CHARS,
        "did": EXIT_NOTE_DID_MAX_CHARS, "cited": EXIT_NOTE_EPISODE_ID_MAX_CHARS,
    }[field]
    values = [f"Ch{text}pel" for text in _YAML_HARD] + [f"{text}Chapel" for text in _YAML_HARD]
    if field == "callsign":
        values += [f"Ch{chr(code)}pel" for code in range(0x180)]
    admitted_seen = refused_seen = 0
    for value in values:
        note = {"cited": ("ep-000", value)} if field == "cited" else {field: value}
        path = await _write_note(records, **note)
        plan = await plan_promotion(records, timeline_id=_SHIP)
        (records.repo_path / path).unlink()
        if is_exit_note_text(value, bound):
            (record,) = plan.records
            stored = {
                "callsign": record.author_callsign, "agent_type": record.author_agent_type, "did": record.author_did,
                "cited": record.source_episode_ids[-1],
            }[field]
            assert stored == value, repr(value)
            admitted_seen += 1
        else:
            assert plan.records == (), repr(value)
            refused_seen += 1
    assert admitted_seen and refused_seen  # premise: both kinds were exercised


def test_a_note_the_rule_refuses_is_withheld_and_the_real_reset_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4 (R2-F2): a stored note whose heading is spelled with a lookalike letter raised ``KeyError`` through the
    rule, the plan and the real ``probos reset``, which exited 1 with nothing wiped. A note that breaks the rule is
    withheld, and the reset runs."""
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    lookalike = exit_note_body("Chapel", "surgeon", _SHIP, _LESSON).replace("## Discussion", "## D\u0131scussion")
    path = asyncio.run(_write_note(_records(data_dir), content=lookalike))

    assert _reset(monkeypatch, config, data_dir) == 0
    assert (path,) not in _rows(tmp_path / "archive.db", "SELECT source_ref FROM archive")


_HUGE = "0x" + "1" * 4000  # A5: a YAML integer whose decimal form is longer than Python's integer-string limit


@pytest.mark.parametrize(
    "source, field",
    [
        ("exit-note", "status"), ("exit-note", "created"), ("exit-note", "updated"), ("finding", "author"),
        ("finding", "status"), ("finding", "department"), ("finding", "created"), ("finding", "updated"),
        ("finding", "topic"),
    ],
)
async def test_a_stored_value_that_cannot_be_shown_as_text_never_stops_the_promotion(
    tmp_path: Path, source: str, field: str,
) -> None:
    """A5 (round 3 R3-M1-2): ``str()`` raises ``ValueError`` for an integer longer than Python's integer-string limit
    (YAML reads ``0x...`` into one), so one stored value stopped the plan and the whole reset. Such a value is archived
    as no value, as a missing one is, and a title falls back to the file name; S1's sources had the same conversions."""
    records = _records(_data_dir(tmp_path))
    if source == "exit-note":
        path = await _write_note(records)
    else:
        path = "notebooks/bones/finding.md"
        await records.write_entry(
            author="Bones", path=path, content="A finding.", message="test: a finding", classification="ship",
            department="medical", topic="Coolant drift", extra_frontmatter={"claim_id": "claim-0001"},
        )
    stored = records.repo_path / path
    raw = stored.read_text(encoding="utf-8")
    assert re.search(rf"(?m)^{field}:", raw)  # premise: the store wrote the field
    stored.write_text(re.sub(rf"(?m)^{field}:.*$", f"{field}: {_HUGE}", raw), encoding="utf-8")

    plan = await plan_promotion(records, timeline_id=_SHIP)

    (record,) = plan.records
    shown = {
        "author": record.author_callsign, "topic": record.title, "status": record.metadata["status"],
        "department": record.metadata.get("department"), "created": record.metadata["record_created"],
        "updated": record.metadata["record_updated"],
    }[field]
    assert shown == ("finding" if field == "topic" else "")


def test_a_note_holding_a_value_that_cannot_be_shown_as_text_is_archived_by_the_real_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A5 (round 3 R3-M1-2): the reviewer's case through the real ``probos reset``, which exited 1 with nothing
    wiped. The note is valid, so the reset archives it, with no status."""
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    path = asyncio.run(_write_note(_records(data_dir)))
    stored = _records(data_dir).repo_path / path
    raw = stored.read_text(encoding="utf-8")
    stored.write_text(re.sub(r"(?m)^status:.*$", f"status: {_HUGE}", raw), encoding="utf-8")

    assert _reset(monkeypatch, config, data_dir) == 0
    assert (path,) in _rows(tmp_path / "archive.db", "SELECT source_ref FROM archive")


async def test_an_exit_note_is_archived_once_whichever_reset_promotes_it(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        first = await promote_ship_records(records, archive, timeline_id=_SHIP)
        again = await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)  # tier 2 keeps Ship's Records
    finally:
        await archive.close()

    assert first.created == (path,)
    assert (again.created, again.present) == ((), (path,))
    assert _rows(tmp_path / "archive.db", "SELECT COUNT(*), MIN(timeline_id) FROM archive") == [(1, _SHIP)]


# --- C1 to C4: the erasure's read, and the Captain's review ---------------------------------------------------------


@pytest.mark.parametrize("state", ["new", "vetoed", "erased", "present", "uncited", "no-archive"])
async def test_the_erasure_read_counts_a_note_only_while_the_next_promotion_would_archive_it(
    tmp_path: Path, state: str,
) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records, cited=() if state == "uncited" else ("ep-000",))
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        record = (await plan_promotion(records, timeline_id=_SHIP)).records[0]
        if state == "vetoed":
            outcome = await archive.veto_source(SourceKind.EXIT_NOTE, path, "not canon", timeline_id=_SHIP)
            assert outcome is VetoOutcome.RECORDED
        elif state in ("erased", "present"):
            assert await archive.promote_entry(record) is PromotionOutcome.CREATED
            if state == "erased":
                entry_id = _rows(tmp_path / "archive.db", "SELECT id FROM archive")[0][0]
                assert await archive.erase_entry(entry_id, "the Captain forgets it") is True
        cited = await exit_note_citations(records, None if state == "no-archive" else archive)
    finally:
        await archive.close()

    expected = {"ep-000": (path,)} if state in ("new", "no-archive") else {}
    assert cited == expected


async def test_a_veto_between_the_citation_read_and_the_promotion_decides_both(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        before = await exit_note_citations(records, archive)
        assert await archive.veto_source(SourceKind.EXIT_NOTE, path, "not canon", timeline_id=_SHIP) is VetoOutcome.RECORDED
        after = await exit_note_citations(records, archive)
        promoted = await promote_ship_records(records, archive, timeline_id=_SHIP)
    finally:
        await archive.close()

    assert before == {"ep-000": (path,)}
    assert after == {}
    assert (promoted.created, promoted.vetoed) == ((), (path,))


class _Unlistable(RecordsStore):
    async def list_entries(self, directory: str = "", **filters: Any) -> list[dict]:
        raise OSError("Ship's Records cannot be listed")


async def test_the_citation_read_raises_when_ship_s_records_cannot_be_listed(tmp_path: Path) -> None:
    records = _Unlistable(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))

    with pytest.raises(OSError):
        await exit_note_citations(records, None)


async def test_ship_s_records_without_exit_notes_cite_nothing(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))  # no exit-notes/ directory at all

    assert await exit_note_citations(records, None) == {}


@pytest.mark.parametrize("case", ["not-a-mapping", "not-utf-8"])
async def test_a_document_the_promotion_skips_is_never_read_as_a_citing_note(tmp_path: Path, case: str) -> None:
    """A1: frontmatter that is not a mapping. ``plan_promotion`` skips the document unread, so it can never be
    archived; the citation read skips it too, instead of raising in ``read_entry`` and stopping every erasure. A2:
    bytes that are not UTF-8 are a property of the file, not of the moment; the promotion never sees the document, and
    the strict read skips it too rather than refusing every erasure while it sits in ``exit-notes/``."""
    records = _records(_data_dir(tmp_path))
    stray = records.repo_path / exit_note_path(_SHIP, "surgeon")
    stray.parent.mkdir(parents=True)
    if case == "not-a-mapping":
        stray.write_text("---\nnot a mapping\n---\nCites: ep-000\n", encoding="utf-8")
    else:
        stray.write_bytes(b"---\nauthor: Chapel\n---\n\xff\xfe Cites: ep-000\n")

    plan = await plan_promotion(records, timeline_id=_SHIP)

    assert (plan.records, plan.withheld) == ((), ())  # premise: the promotion skips it
    assert await exit_note_citations(records, None) == {}


@pytest.mark.parametrize("fault", ["injected", "native"])
async def test_a_note_the_listing_cannot_read_now_is_never_read_as_no_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """A2 (M1-F1, M3-F1): a valid citing note the OS refuses to read at this moment. The real listing meets the
    failure inside its own loop; the citation read raises instead of answering that nothing cites the episode, while
    every other reader of Ship's Records keeps skipping the file as before. Readable again, the note counts."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    note = records.repo_path / path
    with contextlib.ExitStack() as stack:
        if fault == "injected":
            _deny_reading(monkeypatch, note)
        else:
            stack.enter_context(_unreadable(note))
        assert await records.list_entries(EXIT_NOTES_DIR) == []  # premise: the default listing skips it, as before
        with pytest.raises(OSError):
            await exit_note_citations(records, None)
        monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


@pytest.mark.parametrize(
    "fault", ["injected-root", "injected-timeline", "injected-entry-type", "native-root", "native-timeline"],
)
async def test_a_note_directory_the_listing_cannot_list_now_is_never_read_as_no_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """A4 (R2-F1, M3-1): the OS refuses to list ``exit-notes/`` or the timeline directory holding a valid citing note.
    ``Path.rglob`` passes over such a directory, so the strict citation read answered that nothing cites the episode
    and the AD-754 erasure went ahead. The strict listing now raises, and the citation read with it, while the default
    listing never raises, as before. Listable again, the note counts. ``[native-*]``: a share-nothing handle on
    Windows, mode 000 on POSIX (skips only where the account lists it anyway). A5 (R3-M1-1): ``[injected-entry-type]``,
    the OS cannot report the timeline directory's type; ``os.walk`` took it for a file and the read answered ``{}``."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    timeline_directory = (records.repo_path / path).parent
    denied = timeline_directory.parent if fault.endswith("-root") else timeline_directory
    with contextlib.ExitStack() as stack:
        if fault == "injected-entry-type":
            _deny_entry_type(monkeypatch, timeline_directory)
        elif fault.startswith("injected"):
            _deny_listing(monkeypatch, denied)
        else:
            stack.enter_context(_unreadable(denied))
        default = await records.list_entries(EXIT_NOTES_DIR)  # never raises: every other reader is unchanged
        if fault.startswith("native"):
            assert default == []  # premise: the OS itself refused to list the directory
        with pytest.raises(OSError):
            await records.list_entries(EXIT_NOTES_DIR, strict=True)
        with pytest.raises(OSError):
            await exit_note_citations(records, None)
        monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


@pytest.mark.parametrize(
    "directory", ["", EXIT_NOTES_DIR, f"{EXIT_NOTES_DIR}/absent"], ids=["all", "exit-notes", "absent"],
)
async def test_the_strict_listing_lists_exactly_what_the_default_listing_lists(tmp_path: Path, directory: str) -> None:
    """A4, A5: the strict listing lists what the default listing lists, in the same order: nested directories, a
    directory named ``*.md`` (A5: never returned by the walk; the default reads it as no file), another suffix, the
    suffix's case as the platform matches it, ``_archived/``, and a directory that does not exist."""
    records = _records(_data_dir(tmp_path))
    await _write_note(records)
    for relative in (
        "exit-notes/a/b/deep.md", "exit-notes/UPPER.MD", "exit-notes/plain.txt", "_archived/old.md", "top.md",
    ):
        (records.repo_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (records.repo_path / relative).write_text("---\nauthor: Bones\n---\n\nA record.\n", encoding="utf-8")
    (records.repo_path / "exit-notes" / "folder.md").mkdir()

    default = await records.list_entries(directory)

    assert await records.list_entries(directory, strict=True) == default
    assert len(default) >= (0 if directory.endswith("absent") else 2)  # premise: something to list


@pytest.mark.parametrize("kind", sorted(_WALK_FAULTS))
def test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing(tmp_path: Path, kind: str) -> None:
    """A5 (round 3 R3-M1-1): a trace-and-fault matrix over 7.3a's table, not one case per round. A clean walk over a
    real tree records every filesystem operation it makes (each ``os.scandir``, each listing step, the last one
    included, each ``is_dir``); the trace allows nothing else, so an operation added without a row fails here. Then
    each recorded operation fails once with ``kind``: the walk raises that error, except a missing root
    (``FileNotFoundError`` or ``NotADirectoryError`` at the root's open), which lists nothing. Every cell first asserts
    that its fault fired at the operation the clean walk made there."""
    root = tmp_path / "exit-notes"
    _walk_tree(root)
    clean = _Trace()
    found = sorted(_traced_walk(root, clean))
    assert found == sorted(path for path in root.rglob("*.md") if path.is_file())  # rglob's files, on a sound tree
    assert set(clean.operations) == {"open-root", "open-subdirectory", "next", "is_dir"}  # one row each, no other
    for fail_at, operation in enumerate(clean.operations, start=1):
        trace = _Trace(fail_at, _WALK_FAULTS[kind])
        try:
            outcome: Any = sorted(_traced_walk(root, trace))
        except OSError as exc:
            outcome = type(exc)
        assert trace.fired == operation, (fail_at, operation)  # premise: this cell's fault fired where it was aimed
        missing_root = operation == "open-root" and kind in ("absent", "not-a-directory")
        assert outcome == ([] if missing_root else type(_WALK_FAULTS[kind]("cell"))), (fail_at, operation)


@pytest.mark.parametrize("stat", ["stat-ok", "stat-ebadf"])
@pytest.mark.parametrize("kind", ["permission", "io", "absent", "not-a-directory"])
async def test_a_listed_note_the_strict_read_cannot_read_is_never_read_as_no_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, stat: str,
) -> None:
    """A5 (7.3a's table, O5): a listed note whose read fails, with any error, raises from the strict listing and the
    citation read; the default listing still skips it; readable again, it counts. ``[*-stat-ebadf]``: A2's
    ``Path.is_file()`` then answered "not there" (``pathlib`` reads EBADF, ENOENT, ENOTDIR, ELOOP and three Windows
    errors so), and the note was skipped as absent. The strict read no longer asks: the walk's listing decides."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    note = records.repo_path / path
    _deny_reading(monkeypatch, note, error=_WALK_FAULTS[kind](str(note)))
    if stat == "stat-ebadf":
        _deny_stat(monkeypatch, note, OSError(errno.EBADF, "bad file descriptor", str(note)))
    assert await records.list_entries(EXIT_NOTES_DIR) == []  # premise: the default listing skips it, as before
    with pytest.raises(OSError):
        await records.list_entries(EXIT_NOTES_DIR, strict=True)
    with pytest.raises(OSError):
        await exit_note_citations(records, None)
    monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


@pytest.mark.parametrize("error", ["ebadf", "enoent", "eacces"])
async def test_a_listed_note_the_citation_read_cannot_find_again_is_never_read_as_no_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str,
) -> None:
    """A5 (7.3a's table, O6): ``exit_note_citations`` reads each listed note again through ``read_entry``, whose
    ``Path.exists`` answers False for EBADF and ENOENT (and on Windows "the device is not ready"), so a note listed and
    read a moment before came back None and cited nothing. A ship-wide note the strict listing returned and
    ``read_entry`` cannot find now raises. ``[eacces]``: ``exists`` raises itself (the control)."""
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    note = records.repo_path / path
    code = {"ebadf": errno.EBADF, "enoent": errno.ENOENT, "eacces": errno.EACCES}[error]
    _deny_stat(monkeypatch, note, OSError(code, os.strerror(code), str(note)))
    listed = await records.list_entries(EXIT_NOTES_DIR, strict=True)
    assert [entry["path"] for entry in listed] == [path]  # premise: the strict listing listed and read it
    with pytest.raises(OSError):
        await exit_note_citations(records, None)
    monkeypatch.undo()

    assert await exit_note_citations(records, None) == {"ep-000": (path,)}


async def test_the_captain_s_review_lists_an_exit_note_as_a_source_to_be_promoted(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_note(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        review = await review_promotion(records, archive, timeline_id=_SHIP)
    finally:
        await archive.close()

    assert [(pending.record.source_ref, pending.state.outcome) for pending in review.sources] == [
        (path, PromotionOutcome.CREATED),
    ]
    assert review.sources[0].record.source_kind is SourceKind.EXIT_NOTE
