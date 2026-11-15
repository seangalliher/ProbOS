"""Ship's Records: an unrecognised classification is private, and a note with no author has no author.

#1797: a classification that is not exactly one of the four labels (private, department, ship, fleet) -- a misspelling,
a case variant, a value with a blank, a list, a number, a bool, null, a mapping -- is read as private, with the
reader-identity rules applied, by ``RecordsStore.read_entry``, ``RecordsStore.search`` and ``record_is_readable``;
``SemanticKnowledgeLayer.index_record`` indexes a list or a mapping as private, with a WARNING, instead of raising. A
missing key is still ship; a reader that named no identity (None) and the Captain still read such a note.
#1800: a private or department note whose author is missing or empty is refused to the anonymous reader "" on the same
three paths; the Captain still reads it, and its own department still reads a department note.

Real RecordsStore and SemanticKnowledgeLayer on ``tmp_path``; every note is a hand-made file with a distinct name per
case (Windows folds case in file names). A case marked ``until_built("#N")`` failed on the base at its own assert; the
milestone that builds #N adds it to ``_BUILT``, after which the marker does nothing.
``RECORDS_READER_GATES_RUNXFAIL=1`` runs every case plainly.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore, record_is_readable
from probos.knowledge.semantic import SemanticKnowledgeLayer

_BUILT: frozenset[str] = frozenset({"#1797", "#1800"})


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("RECORDS_READER_GATES_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


#: Each reader and the department it reads with. alice is the author of every note here that names one.
_READERS: dict[str, str] = {"alice": "engineering", "bob": "medical", "carol": "engineering", "": "", "captain": ""}
_PATHS = ("read_entry", "search", "record_is_readable")
_BODY = "warp coil alignment notes"
_ALICE = "author: alice\ndepartment: engineering"

_UNRECOGNISED = [
    pytest.param("misspelt", "classification: privte", id="misspelt"),
    pytest.param("upper-private", "classification: PRIVATE", id="upper-private"),
    pytest.param("upper-ship", "classification: SHIP", id="upper-ship"),
    pytest.param("blank-ship", 'classification: " ship"', id="quoted-with-a-blank"),
    pytest.param("list-private", "classification: [private]", id="list-private"),
    pytest.param("list-ship", "classification: [ship]", id="list-ship"),
    pytest.param("number", "classification: 3", id="number"),
    pytest.param("bool", "classification: true", id="bool"),
    pytest.param("null", "classification: null", id="null"),
    pytest.param("mapping", "classification: {level: ship}", id="mapping"),
]

_AUTHORLESS = [
    pytest.param("private-no-author", "department: engineering\nclassification: private", {"captain"},
                 id="private-no-author"),
    pytest.param("private-empty-author", 'author: ""\ndepartment: engineering\nclassification: private', {"captain"},
                 id="private-empty-author"),
    pytest.param("department-no-author", "department: engineering\nclassification: department",
                 {"alice", "carol", "captain"}, id="department-no-author"),
]


@pytest.fixture
async def store(tmp_path: Path) -> RecordsStore:
    records = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await records.initialize()
    return records


@pytest.fixture
async def layer(tmp_path: Path) -> AsyncIterator[SemanticKnowledgeLayer]:
    semantic = SemanticKnowledgeLayer(db_path=tmp_path / "semantic", episodic_memory=None)
    await semantic.start()
    try:
        yield semantic
    finally:
        await semantic.stop()


def _note(store: RecordsStore, name: str, frontmatter: str) -> str:
    """A hand-made note ``reports/<name>.md`` with this frontmatter text and LF line endings; its records path."""
    path = f"reports/{name}.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(f"---\n{frontmatter}\nstatus: draft\n---\n\n{_BODY}\n".encode("utf-8"))
    return path


async def _admitted(store: RecordsStore, path: str, scope: str) -> dict[str, set[str]]:
    """The readers each keyword path admits to ``path`` at ``scope``; the predicate reads the store's own parse."""
    whole = await store.read_entry(path, reader_id="captain")
    assert whole is not None, "premise: the Captain reads the note"
    frontmatter = whole["frontmatter"]
    admitted: dict[str, set[str]] = {name: set() for name in _PATHS}
    for reader, department in _READERS.items():
        if await store.read_entry(path, reader_id=reader, reader_department=department) is not None:
            admitted["read_entry"].add(reader)
        hits = await store.search("warp", scope=scope, reader_id=reader, reader_department=department)
        if path in [hit["path"] for hit in hits]:
            admitted["search"].add(reader)
        if record_is_readable(frontmatter, scope=scope, reader_id=reader, reader_department=department):
            admitted["record_is_readable"].add(reader)
    return admitted


async def _assert_premise(store: RecordsStore) -> None:
    """Asserted first: alice's private note is refused to bob and to "" on every path; a ship note is shown to bob."""
    private = await _admitted(store, _note(store, "control-private", _ALICE + "\nclassification: private"), "ship")
    ship = await _admitted(store, _note(store, "control-ship", _ALICE + "\nclassification: ship"), "ship")
    for reader_path in _PATHS:
        assert not {"bob", ""} & private[reader_path], f"premise: {reader_path} refuses the private control to bob and ''"
        assert "bob" in ship[reader_path], f"premise: {reader_path} shows the ship control to bob"


@until_built("#1797")
@pytest.mark.parametrize(("kind", "line"), _UNRECOGNISED)
async def test_an_unrecognised_classification_is_private_on_every_keyword_path(
    store: RecordsStore, kind: str, line: str,
) -> None:
    """#1797 acceptance 1: alice (the author) and the Captain are admitted; bob (medical), carol (engineering, alice's
    department: the note is private, not department) and the anonymous reader are refused, on all three paths."""
    await _assert_premise(store)
    path = _note(store, f"odd-{kind}", f"{_ALICE}\n{line}")
    assert await _admitted(store, path, "ship") == {name: {"alice", "captain"} for name in _PATHS}


@pytest.mark.parametrize(("kind", "line"), _UNRECOGNISED)
async def test_a_reader_that_named_no_identity_still_reads_an_unrecognised_classification(
    store: RecordsStore, kind: str, line: str,
) -> None:
    """#1797 (the Captain's decision): ``reader_id=None`` reads at scope level only. The note is level 0, so it is read at
    every scope and found by the search. A control: it passes on the base and guards that the floor is private."""
    path = _note(store, f"none-{kind}", f"{_ALICE}\n{line}")
    whole = await store.read_entry(path, reader_id="captain")
    assert whole is not None
    for scope in ("private", "department", "ship", "fleet"):
        assert record_is_readable(whole["frontmatter"], scope=scope, reader_id=None) is True, scope
    assert path in [hit["path"] for hit in await store.search("warp", reader_id=None)]


@pytest.mark.parametrize(("kind", "line", "readers"), [
    pytest.param("private", "classification: private", {"alice", "captain"}, id="private"),
    pytest.param("department", "classification: department", {"alice", "carol", "captain"}, id="department"),
    pytest.param("ship", "classification: ship", set(_READERS), id="ship"),
    pytest.param("fleet", "classification: fleet", set(_READERS), id="fleet"),
    pytest.param("missing", "", set(_READERS), id="missing-key"),
])
async def test_the_four_labels_and_a_missing_key_read_as_before(
    store: RecordsStore, kind: str, line: str, readers: set[str],
) -> None:
    """Controls (they pass on the base): each label, and a note with no classification key (ship), read as before. Read at
    ``fleet`` scope so that the fleet note is in scope."""
    path = _note(store, f"label-{kind}", f"{_ALICE}\n{line}" if line else _ALICE)
    assert await _admitted(store, path, "fleet") == {name: readers for name in _PATHS}


@until_built("#1797")
@pytest.mark.parametrize("value", [pytest.param(["private"], id="list"), pytest.param({"level": "ship"}, id="mapping")])
async def test_index_record_indexes_a_list_or_a_mapping_as_private_with_a_warning(
    layer: SemanticKnowledgeLayer, caplog: pytest.LogCaptureFixture, value: Any,
) -> None:
    """#1797 acceptance 3: on the base the membership test raised ``TypeError`` (a list or a dict is unhashable), so the
    backfill left such a note keyword-only, where every reader read it."""
    path = "reports/index-odd.md"
    raised: BaseException | None = None
    with caplog.at_level(logging.WARNING, logger="probos.knowledge.semantic"):
        try:
            await layer.index_record(
                path=path, content=_BODY, classification=value, author="alice", department="engineering",
            )
        except TypeError as exc:
            raised = exc
    assert raised is None, f"index_record raised {raised!r}"
    rows = await layer.search("warp", types=["records"], limit=10, records_scope="ship")
    stored = [(row.get("metadata") or {}).get("classification") for row in rows
              if (row.get("metadata") or {}).get("path") == path]
    assert stored == ["private"]
    assert [record for record in caplog.records
            if record.levelno == logging.WARNING and path in record.getMessage()], "a WARNING names the path"


@until_built("#1800")
@pytest.mark.parametrize(("kind", "frontmatter", "readers"), _AUTHORLESS)
async def test_a_note_with_no_author_is_refused_to_the_anonymous_reader(
    store: RecordsStore, kind: str, frontmatter: str, readers: set[str],
) -> None:
    """#1800: the anonymous reader "" was admitted by authorship ("" equalled the missing or empty author) on all three
    paths. Only the Captain reads the private notes now; the department note's own department (alice and carol,
    engineering) still reads it by the department rule; bob (medical) and "" are refused."""
    await _assert_premise(store)
    path = _note(store, f"authorless-{kind}", frontmatter)
    assert await _admitted(store, path, "ship") == {name: readers for name in _PATHS}
