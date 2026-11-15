# Ship's Records reader gates: an unrecognised classification is private, a note with no author has no author -- #1797, #1800, one batch

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14
**Amended:** `claude-architect`, 2026-11-15 (F-b3-1): P2a-10's unhashable case is an authored record, so it tests #1797 alone and M2a is green; G2a states `test_bf679...`'s 0 failed. No count changes.
**File in the repository:** `prompts/bf-966-969-records-reader-gates.md`. No commit subject or tracker line of this batch carries an `AD-` or `BF-` token, or this file's name (section 5).
**Status:** ready to build on `origin/main` after #1794, batch 1 (note-taker, file writer) and batch 2 (agentic loop) merge. Read on `5275d008`. None of them edits the four files below. The trackers move, but their anchors do not (M3).
**Dependencies:** none in code. **Numbers:** #1797 is BF-966 and #1800 is BF-969 (`gh issue view`). Nothing is allocated here.
**Builder:** `claude-sonnet-5.5`. At most about 150 tool calls per milestone. Focused tests only; search first, then read the range. **Diff Reviewer:** `gpt-6.1-sol` (section 9).
**Estimated tests (expected, not measured):**
- One new file, `tests/test_bf966_unrecognised_classification.py`, with 30 cases: 15 strict xfail at M1 and 15 controls.
- `tests/test_bf679_oracle_records_reader_identity.py` gains one parity test (18 cases) and changes four cases.
- `tests/test_bf940_frontmatter_framing.py` changes one case.
- No test function is removed.

**Base blobs (`5275d008`; the index is LF, and this worktree checks out CRLF: `git ls-files --eol` gives `i/lf w/crlf`).**

| File | Blob | Role |
|---|---|---|
| `src/probos/knowledge/records_store.py` | `2a99529c8566f7b00d543d3240b3cc4a3faf1c5f` | edited (M2a, M2b) |
| `src/probos/knowledge/semantic.py` | `2c90f55c6faafd99fd17db64d8076113655f6f38` | edited (M2a, M2b) |
| `tests/test_bf679_oracle_records_reader_identity.py` | `f50e61fb4e69704deffdfa0b7122a68daaeb6bc8` | edited (M2a, M2b) |
| `tests/test_bf940_frontmatter_framing.py` | `d6f5a85d7520c87fcc48e7a698f06eddc3565625` | edited (M2a) |
| `PROGRESS.md`, `DECISIONS.md` | `3e87baf3...`, `675bdc29...` | move as the earlier batches merge; anchors in M3 |

## 1. Problem (re-derived on `5275d008`)

| Issue | Evidence | Verdict |
|---|---|---|
| #1797: the predicate opens an odd label | `records_store.py:174-187`: a non-label string gets level 0 (`.get(doc_class, 0)`), and a non-`str` value gets level 0 too (`is_labelled` False). Both skip the identity gate (`:186`) | Holds |
| #1797: read_entry opens an odd label | `records_store.py:1527` (`doc_class = gate.get(...)`), `:1531`, `:1533`: only `== "private"` and `== "department"` are refused | Holds |
| #1797: search uses the predicate | `records_store.py:421` (`_base_reading_admits`) and `:515` | Holds |
| #1797: the index disagrees and raises | `semantic.py:395-401`: a non-label is indexed as private, but a list or a dict raises `TypeError` at `in`. The backfill catches it (`:767-771`), so the note stays keyword-only | Holds |
| #1797: the house rule | `security/classification.py:123`: "source unknown -> most restrictive (private=0)" | Holds |
| #1800: author defaults to "" | `records_store.py:189-191` and `:1528`/`:1531`/`:1533`. `semantic.py:116` (`{"author": reader_id}`) and `:760` (`... or ""`) | Holds |
| #1800: precedent | `records_store.py:113-124` (`_unparsed_gate`: author `None`) | Holds |
| *New:* five existing cases pin the old behaviour | `test_bf679...:527-536`, `:544-550`, `:630-634`, `:636-639`; `test_bf940_frontmatter_framing.py:293` | Required edits (P2a-10, P2a-11, P2b-7, P2b-8) |

## 2. Solution and decisions

- **M1** adds the new test file. It uses a real `RecordsStore` and a real `SemanticKnowledgeLayer` on `tmp_path`, and hand-made notes. Each built case is strict xfail per issue, and each M2 milestone adds its issue to `_BUILT`.
  - M1 edits no existing test. Every existing-test edit of this batch changes an expected value, so each lands in the milestone that builds the behaviour it pins. The parity test lands there too.
- **M2a (#1797):**
  - `records_store.effective_classification(value: object) -> str` is public and never raises. It returns `value` when `type(value) is str and value in _CLASSIFICATION_LEVELS`, and `"private"` otherwise. Each caller keeps its own `"ship"` default for a missing key.
  - `record_is_readable` and `read_entry` read through it. The `is_labelled` branch is dropped.
  - `index_record` reads through it and WARNs when the result differs from the input (`%r`), so a list or a mapping no longer raises.
  - `build_records_scope_filter`: docstring invariant only, with no logic change and no `$nin` clause.
- **M2b (#1800):**
  - The private `_author_identity(value: object) -> str | None` returns the value when it is a non-empty `str`, and `None` otherwise. `record_is_readable` and `read_entry` compare the reader with it.
  - `build_records_scope_filter` emits no author clause when `reader_id == ""`. The open labels and the department clause are unchanged.
- **Rejected:**
  - Patching each copy in place: three copies drift again, which is how the paths came to disagree.
  - `read_entry` calling `record_is_readable`: it would change `read_entry`'s documented department rule (`records_store.py:165-172`).
  - A `$nin` clause: it is dead code behind the normalisation, and it could only loosen.
  - Refusing an empty author in `write_entry`: it would not reach a hand-made note, and the readers must hold either way. Considered, deferred.

## 3. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`, run from the repository root, always with `-n 0 -p no:randomly`.

**Focused set `G2`** (the consumer search is in section 11):
- **Edited:**
  - the new file;
  - `tests/test_bf679_oracle_records_reader_identity.py`;
  - `tests/test_bf940_frontmatter_framing.py`.
- **Unedited, must stay green:**
  - `tests/test_ad1138_records_semantic_index.py`, which includes `test_unknown_classification_normalizes_to_private`;
  - `tests/test_ad1157_notebook_classification.py`, which includes `test_an_unreadable_stored_classification_falls_back`;
  - `tests/test_bf684_records_index_coverage.py`;
  - `tests/test_bf940_s4_unparsed_frontmatter.py`;
  - `tests/test_bf952_records_keyword_search.py`;
  - `tests/test_records_store.py` (its `def` name duplicate scan, `:422-434`);
  - `tests/test_ad1140_publish_finding.py`;
  - `tests/test_ad1179_vocabulary_constants.py`;
  - `tests/test_layer_boundaries.py`;
  - `tests/test_ad1346_admission_store_family_census.py`;
  - `tests/test_ad1346_admission_store_census.py`;
  - `tests/test_ad1346_admission_file_write_census.py`;
  - `tests/test_ad1341_s1_promotion.py`;
  - `tests/test_ad1341_s4_lessons.py`;
  - `tests/test_ad1341_s5_after_action.py`;
  - `tests/test_ad1341_s5_continuous_promotion.py`;
  - `tests/test_bf959_records_readers_containment.py`.

**The Builder's gates (focused tests only):**
- **M0:** record the `--collect-only -q` count of every existing file in G2.
- **G1 (M1):** `PY -m pytest tests/test_bf966_unrecognised_classification.py -q -n 0 -p no:randomly`.
  - **Expected:** **15 passed, 15 xfailed.**
  - Then set `$env:RECORDS_READER_GATES_RUNXFAIL = "1"`, run the file alone, and `Remove-Item Env:RECORDS_READER_GATES_RUNXFAIL`. Expect 15 failed, 15 passed, every failure at its own `assert` (none at an import, a fixture or a call).
  - An XPASS is a FAIL; report it to the Architect.
- **G2a (M2a):**
  - Run G2. The new file gives 27 passed and 3 xfailed (#1800).
  - `test_bf679...` has its M0 count + 18 and 0 failed. Every other file has its M0 count and 0 failed.
  - Then `PY -P scripts/check_architecture_principles.py --check`.
- **G2b (M2b):**
  - Run G2. The new file gives 30 passed and 0 xfailed.
  - `test_bf679...` has its M0 count + 18 and 0 failed. Every other file has its M0 count and 0 failed. Then the architecture check again.
- **G3 (M3):**
  - `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
  - No AD or BF number moves. A changed number row is a hard stop for the Architect.

**The orchestrator's steps:**
1. The oracle: every SEARCH applies exactly once, in label order.
2. The mutation campaign (section 7).
3. Then, once: `PY scripts/run_test_gate.py --label records-reader-gates --receipt logs/gates/records-reader-gates.receipt.json`.

**Harness rule.** No source change to make a test pass, no new skip, and no loosened assertion. If any expected count differs, stop and report to the Architect; the census files count most.

## 4. The contract

The SEARCH text is LF and ASCII, as in the index blob. It starts at a line start and matches exactly once in its file, once the earlier blocks for that file have been applied in label order. A label names its file by full path.

The non-ASCII lines of the edited files lie outside every SEARCH:
- `records_store.py:145`, `:149`, `:156`, `:158`, `:161`, `:162`, `:1520`;
- `semantic.py:49`, `:58`, `:62`, `:85`;
- `test_bf679...:7`, `:11`, `:231`.

`semantic.py:383` and `:385` hold the six-character escape `\u2014`, not the character, and P2a-7 matches it as written.

### M1

**N1-1.** New file `tests/test_bf966_unrecognised_classification.py`. It imports only names that exist on the base.

```python
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

_BUILT: frozenset[str] = frozenset()


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
```

**How the built cases fail on the base (expected):**
- Unrecognised: bob, carol and "" are admitted on every path.
- Index: `TypeError`, so `raised is None` fails.
- Authorless: "" is admitted on every path (and for the department note, so is the departmentless read of ""; the sets differ).

### M2a (#1797)

**P2a-1** (`src/probos/knowledge/records_store.py`: the helper)
SEARCH:
```
FRONTMATTER_UNPARSED_KEY = "frontmatter_unparsed"
```
REPLACE:
```
FRONTMATTER_UNPARSED_KEY = "frontmatter_unparsed"


def effective_classification(value: object) -> str:
    """BF-966 (#1797): the classification the access rules apply to a stored ``value``. Never raises.

    ``value`` itself when it is exactly one of the four labels of ``_CLASSIFICATION_LEVELS`` (a ``str``, compared as
    written: no case-folding, no stripping); ``"private"`` for anything else (a misspelling, a case variant, a list, a
    mapping, a number, a bool, ``None``), as ``security.classification`` reads an unknown source label as the most
    restrictive. The caller applies its own default for a missing key first (``frontmatter.get("classification",
    "ship")``). ``knowledge.semantic`` imports it, so the index and the keyword readers apply one rule.
    """
    if type(value) is str and value in _CLASSIFICATION_LEVELS:
        return value
    return "private"
```

**P2a-2** (`src/probos/knowledge/records_store.py`: `record_is_readable`'s docstring)
SEARCH:
```
      ``level(classification) <= level(scope)``. An unrecognised record
      classification defaults to level ``0`` and an unrecognised ``scope`` to
      level ``2``.
```
REPLACE:
```
      ``level(classification) <= level(scope)``. BF-966 (#1797): a record
      classification that is not exactly one of the four labels (of any type)
      reads as ``private`` (:func:`effective_classification`), so it is
      identity-gated too; a missing one is ``ship``. An unrecognised ``scope``
      is level ``2``.
```

**P2a-3** (`src/probos/knowledge/records_store.py`: `record_is_readable`'s body)
SEARCH:
```
    doc_class = frontmatter.get("classification", "ship")
    # A non-str classification takes the same level-0 default ``search`` has
    # always applied; the explicit type check additionally survives an
    # unhashable value rather than raising out of the scan, and keeps such a
    # record out of the identity-gated set (it is not one of the four labels).
    is_labelled = type(doc_class) is str
    doc_level = _CLASSIFICATION_LEVELS.get(doc_class, 0) if is_labelled else 0
    if doc_level > _CLASSIFICATION_LEVELS.get(scope, 2):
        return False

    if reader_id is None or reader_id == _UNRESTRICTED_READER:
        return True
    if not is_labelled or doc_class not in _IDENTITY_GATED_CLASSIFICATIONS:
        return True
```
REPLACE:
```
    # BF-966 (#1797): a classification that is not exactly one of the four labels
    # (a misspelling, a case variant, a list, a number, null) is read as private,
    # so it is identity-gated; a missing one is ship. The helper never raises, so
    # an unhashable value cannot end the scan.
    doc_class = effective_classification(frontmatter.get("classification", "ship"))
    if _CLASSIFICATION_LEVELS[doc_class] > _CLASSIFICATION_LEVELS.get(scope, 2):
        return False

    if reader_id is None or reader_id == _UNRESTRICTED_READER:
        return True
    if doc_class not in _IDENTITY_GATED_CLASSIFICATIONS:
        return True
```

**P2a-4** (`src/probos/knowledge/records_store.py`: `read_entry`)
SEARCH:
```
            doc_class = gate.get("classification", "ship")
```
REPLACE:
```
            # BF-966 (#1797): a classification that is not exactly one of the four labels is private.
            doc_class = effective_classification(gate.get("classification", "ship"))
```

**P2a-5** (`src/probos/knowledge/semantic.py`: the import)
SEARCH:
```
    _UNRESTRICTED_READER,  # BF-679: owned by the store
)
```
REPLACE:
```
    _UNRESTRICTED_READER,  # BF-679: owned by the store
    effective_classification,  # BF-966 (#1797): owned by the store; the index applies the keyword readers' rule
)
```

**P2a-6** (`src/probos/knowledge/semantic.py`: the filter's invariant)
SEARCH:
```
    two** expressions. So a lone predicate is always emitted flat.

    Returns:
```
REPLACE:
```
    two** expressions. So a lone predicate is always emitted flat.

    BF-966 (#1797): the index holds only the four labels, because
    :meth:`SemanticKnowledgeLayer.index_record` normalises through
    ``effective_classification``. A stored odd label would match none of the
    ``$in`` lists below and so be withheld from every reader, stricter than
    ``private``. No ``$nin`` clause is added: behind the normalisation it is
    dead code, and it could only loosen.

    Returns:
```

**P2a-7** (`src/probos/knowledge/semantic.py`: `index_record`'s docstring)
SEARCH:
```
        :func:`build_records_scope_filter`). An unrecognised classification is
        normalised to ``\"private\"`` \u2014 level 0, matching the
        ``_CLASSIFICATION_LEVELS.get(doc_class, 0)`` default in
        ``RecordsStore.search`` \u2014 so an odd label is never silently treated as
        broadly readable.
```
REPLACE:
```
        :func:`build_records_scope_filter`). BF-966 (#1797): a classification
        that is not exactly one of the four labels, of any type, is indexed as
        ``private`` through ``records_store.effective_classification``, the rule
        the keyword readers apply, with a WARNING. So the index holds only the
        four labels, and an odd label is never treated as broadly readable.
```

**P2a-8** (`src/probos/knowledge/semantic.py`: `index_record`'s body)
SEARCH:
```
        if classification not in _CLASSIFICATION_LEVELS:
            logger.warning(
                "AD-1138: record %s has unknown classification %r; indexing it as "
                "'private' so scope filtering stays conservative",
                path, classification,
            )
            classification = "private"
```
REPLACE:
```
        # BF-966 (#1797): the keyword readers' rule. It never raises, so a list or a mapping is indexed as
        # private instead of raising out of the backfill (which left the note keyword-only).
        effective = effective_classification(classification)
        if effective != classification:
            logger.warning(
                "AD-1138: record %s has unknown classification %r; indexing it as "
                "'private' so scope filtering stays conservative",
                path, classification,
            )
        classification = effective
```

**P2a-9** (`tests/test_bf679_oracle_records_reader_identity.py`: the parity test; acceptance 2 of #1797, and the parity line of #1800)
SEARCH:
```
        keyword = await _keyword_paths(records, reader_id, department)
        semantic = await _semantic_paths(layer, reader_id, department)

        assert keyword == semantic

    @pytest.mark.parametrize(
        "agent_id", ["", "captain", "agent-alice", "agent-bob", "agent-erin", "ghost"],
    )
```
REPLACE:
```
        keyword = await _keyword_paths(records, reader_id, department)
        semantic = await _semantic_paths(layer, reader_id, department)

        assert keyword == semantic

    @pytest.mark.parametrize("reader_id", _ALL_READERS)
    @pytest.mark.parametrize("department", _ALL_DEPARTMENTS)
    async def test_hand_made_notes_are_admitted_alike_after_a_backfill(
        self, records, layer, reader_id: str | None, department: str,
    ) -> None:
        """BF-966 (#1797) and BF-969 (#1800): hand-made notes with an unrecognised classification, and private or
        department notes with no author, are admitted alike by the keyword predicate and the ChromaDB filter once the
        backfill has indexed them. The premise comes first: on the base the list-valued note raised out of
        ``index_record``, so the backfill left it keyword-only, where every reader read it."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        hand_made = {
            "reports/hand-misspelt.md": "author: alice\ndepartment: engineering\nclassification: privte",
            "reports/hand-list.md": "author: alice\ndepartment: engineering\nclassification: [private]",
            "reports/hand-null.md": "author: alice\ndepartment: engineering\nclassification: null",
            "reports/hand-number.md": "author: alice\ndepartment: engineering\nclassification: 3",
            "reports/hand-private-no-author.md": "department: engineering\nclassification: private",
            "reports/hand-private-empty-author.md": 'author: ""\ndepartment: engineering\nclassification: private',
            "reports/hand-department-no-author.md": "department: engineering\nclassification: department",
        }
        for path, frontmatter in hand_made.items():
            (records.repo_path / path).write_bytes(
                f"---\n{frontmatter}\n---\n\nreactor notes kept by hand\n".encode("utf-8"),
            )
        await layer.reindex_records(records)
        assert "reports/hand-list.md" in await _semantic_paths(layer, None), "premise: the list-valued note is indexed"

        keyword = await _keyword_paths(records, reader_id, department)
        semantic = await _semantic_paths(layer, reader_id, department)

        assert keyword == semantic

    @pytest.mark.parametrize(
        "agent_id", ["", "captain", "agent-alice", "agent-bob", "agent-erin", "ghost"],
    )
```

**P2a-10** (`tests/test_bf679_oracle_records_reader_identity.py`: two predicate cases)
SEARCH:
```
    def test_unknown_classification_takes_the_level_zero_default(self) -> None:
        """Byte-identical to the pre-BF-679 inline check in ``search``."""
        assert record_is_readable(
            {"classification": "top-secret"}, scope="private", reader_id=None,
        ) is True

    def test_unhashable_classification_does_not_raise(self) -> None:
        assert record_is_readable(
            {"classification": ["private"]}, scope="ship", reader_id="",
        ) is True
```
REPLACE:
```
    def test_unknown_classification_is_private_and_identity_gated(self) -> None:
        """BF-966 (#1797): an unrecognised label reads as ``private``. It is still level 0, so a reader that
        named no identity reads it at every scope; it is now identity-gated, so the anonymous reader is refused
        it and its author is not. Renamed from ``..._takes_the_level_zero_default``, whose "byte-identical to
        search" no longer holds."""
        assert record_is_readable(
            {"classification": "top-secret"}, scope="private", reader_id=None,
        ) is True
        assert record_is_readable(
            {"classification": "top-secret", "author": "alice"}, scope="ship", reader_id="",
        ) is False
        assert record_is_readable(
            {"classification": "top-secret", "author": "alice"}, scope="ship", reader_id="alice",
        ) is True

    def test_unhashable_classification_is_private_and_does_not_raise(self) -> None:
        """BF-966 (#1797): a list is not one of the four labels, so it reads as ``private``: an authored note is
        refused to the anonymous reader (which it was not: level 0 and not identity-gated), read by its author, and
        still read by a reader that named no identity. The note has an author so this case tests #1797 alone; the
        authorless note is #1800's (``test_bf966_unrecognised_classification.py``, ``private-no-author``).
        Renamed from ``..._does_not_raise``."""
        assert record_is_readable(
            {"classification": ["private"], "author": "alice"}, scope="ship", reader_id="",
        ) is False
        assert record_is_readable(
            {"classification": ["private"], "author": "alice"}, scope="ship", reader_id="alice",
        ) is True
        assert record_is_readable(
            {"classification": ["private"], "author": "alice"}, scope="ship", reader_id=None,
        ) is True
```

**P2a-11** (`tests/test_bf940_frontmatter_framing.py`: the first framing case)
SEARCH:
```
            {"author": "alice", "classification": "private --- inline", "status": "nominal"}, "warp notes", {"alice", "bob"},
```
REPLACE:
```
            {"author": "alice", "classification": "private --- inline", "status": "nominal"}, "warp notes", {"alice"},
```

**P2a-12** (`tests/test_bf940_frontmatter_framing.py`: its reason)
SEARCH:
```
        it (F2): the readers listed are the ones shown the record. No writer in the repository makes such a document."""
```
REPLACE:
```
        it (F2): the readers listed are the ones shown the record. No writer in the repository makes such a document.
        BF-966 (#1797) amends L3 for the 1st: its classification, ``private --- inline``, is not one of the four labels,
        so it is read as private and bob is refused it. The repeated-key half of L3 (the 3rd) is unchanged."""
```

**P2a-13** (`tests/test_bf966_unrecognised_classification.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset()
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1797"})
```

### M2b (#1800)

**P2b-1** (`src/probos/knowledge/records_store.py`: the author helper)
SEARCH:
```
def _unparsed_gate(rel_path: str) -> dict[str, Any]:
```
REPLACE:
```
def _author_identity(value: object) -> str | None:
    """BF-969 (#1800): the reader id a record's ``author`` value admits. The value when it is a non-empty ``str``;
    otherwise ``None``, which equals no reader id (the anonymous ``""`` included), as :func:`_unparsed_gate`'s ``None``
    author does. Never raises."""
    if type(value) is str and value:
        return value
    return None


def _unparsed_gate(rel_path: str) -> dict[str, Any]:
```

**P2b-2** (`src/probos/knowledge/records_store.py`: `record_is_readable`'s docstring)
SEARCH:
```
      author, so identity-gated classifications are withheld. This is the
      fail-closed state the Oracle uses for a caller it cannot identify.
```
REPLACE:
```
      author, so identity-gated classifications are withheld. This is the
      fail-closed state the Oracle uses for a caller it cannot identify.
      BF-969 (#1800): an author that is empty or not a ``str`` is nobody
      (:func:`_author_identity`), so ``""`` is never a record's author.
```

**P2b-3** (`src/probos/knowledge/records_store.py`: `record_is_readable`'s author)
SEARCH:
```
    doc_author = frontmatter.get("author", "")
```
REPLACE:
```
    # BF-969 (#1800): an empty or non-str author is nobody, so it admits no reader, "" included.
    doc_author = _author_identity(frontmatter.get("author"))
```

**P2b-4** (`src/probos/knowledge/records_store.py`: `read_entry`'s author)
SEARCH:
```
            doc_author = gate.get("author", "")
```
REPLACE:
```
            doc_author = _author_identity(gate.get("author"))  # BF-969 (#1800): an empty or non-str author is nobody
```

**P2b-5** (`src/probos/knowledge/semantic.py`: the filter's docstring)
SEARCH:
```
    ``""`` means an **anonymous** reader and runs the identity layer with an
    empty author, so the identity-gated classifications are withheld. Before
```
REPLACE:
```
    ``""`` means an **anonymous** reader: it is nobody's author, so it gets no
    author clause (BF-969, #1800), and the identity-gated classifications are
    withheld but for a ``department`` record of its own department. Before
```

**P2b-6** (`src/probos/knowledge/semantic.py`: the author clause)
SEARCH:
```
    if gated_labels:
```
REPLACE:
```
    # BF-969 (#1800): the anonymous reader "" is nobody's author, so it gets no author clause; a note stored with
    # author "" then matches no reader by authorship, as record_is_readable and read_entry read it.
    if gated_labels and reader_id:
```

**P2b-7** (`tests/test_bf679_oracle_records_reader_identity.py`: the anonymous filter at ship scope)
SEARCH:
```
    def test_anonymous_reader_emits_the_identity_layer(self) -> None:
        """The one-line defect: ``""`` used to take the unrestricted branch."""
        where = build_records_scope_filter("ship", reader_id="")

        assert "$or" in where
        assert {"classification": {"$in": ["ship"]}} in where["$or"]
        assert {"$and": [
            {"classification": {"$in": ["private", "department"]}},
            {"author": ""},
        ]} in where["$or"]
```
REPLACE:
```
    def test_anonymous_reader_is_given_the_open_labels_only(self) -> None:
        """The one-line defect: ``""`` used to take the unrestricted branch. BF-969 (#1800): it is nobody's
        author, so it gets no author clause (it was ``{"author": ""}``, which admitted a note with no author).
        With no department it is given the open labels only. Renamed from ``..._emits_the_identity_layer``."""
        where = build_records_scope_filter("ship", reader_id="")

        assert where != build_records_scope_filter("ship", reader_id=None)
        assert where == {"classification": {"$in": ["ship"]}}
        assert build_records_scope_filter(
            "ship", reader_id="", reader_department="engineering",
        ) == {"$or": [
            {"classification": {"$in": ["ship"]}},
            {"$and": [{"classification": "department"}, {"department": "engineering"}]},
        ]}
```

**P2b-8** (`tests/test_bf679_oracle_records_reader_identity.py`: the anonymous filter at private scope)
SEARCH:
```
    def test_anonymous_reader_at_private_scope_stays_flat(self) -> None:
        """Only one clause survives, so it must not be wrapped in a 1-element $or."""
        where = build_records_scope_filter("private", reader_id="")

        assert where == {"$and": [
            {"classification": {"$in": ["private"]}}, {"author": ""},
        ]}
```
REPLACE:
```
    def test_anonymous_reader_at_private_scope_admits_nothing(self) -> None:
        """BF-969 (#1800): at ``private`` scope the only clause was ``{"author": ""}``, which is gone, so nothing
        is admitted and the caller skips the query (``None``; ``SemanticKnowledgeLayer.search`` does). Renamed
        from ``..._stays_flat``."""
        assert build_records_scope_filter("private", reader_id="") is None
```

**P2b-9** (`tests/test_bf966_unrecognised_classification.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset({"#1797"})
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1797", "#1800"})
```

### M3: trackers and ledger

Apply M3 last, after the earlier batches merge. Replace `DATE` with M3's date. No line carries an `AD-` or `BF-` token or this contract's file name.

**P3-1** (`PROGRESS.md`). The anchor is the title line and the blank line after it. It does not move: every earlier batch inserts below it, so this entry lands on top, above theirs.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**Ship's Records reads a classification that is not one of the four labels as private, and a note with no author admits no reader by authorship (DATE), #1797 #1800.**
- **Base.** `record_is_readable` gave an unrecognised classification (a misspelling, a case variant, a list, a number, null) level 0 and no identity check, and `read_entry` refused only `private` and `department`, so the keyword search, `read_entry` and the predicate showed such a note to every reader. The semantic index stored an odd string as private but raised on a list or a mapping, which left that note keyword-only. A private or department note whose author was missing or empty was shown to the anonymous reader `""` on all three paths, because `""` equalled the author's default.
- **Change.** `records_store.effective_classification` returns a value only when it is exactly one of the four labels, and `private` otherwise. `record_is_readable`, `read_entry` and `SemanticKnowledgeLayer.index_record` all read through it; a missing key is still `ship`, and a reader that named no identity and the Captain still read at scope level. An author that is empty or not a string is nobody on the keyword paths, and the semantic filter gives the anonymous reader no author clause. A new test file drives the three readers and the index with hand-made notes. The parity matrix gains hand-made notes after a backfill, and five existing cases change, each with its reason inline. Refs #1797, #1800.

```

**P3-2** (`DECISIONS.md`). The anchor is the heading below, at line 1796 on `5275d008`. #1794 and batch 1 insert their entries before it too, so this entry lands after theirs. The heading itself is unchanged.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### Ship's Records: a classification that is not one of the four labels is private, and a note with no author has no author (DATE, #1797, #1800)

- *Scope.* `knowledge/records_store.py` (`effective_classification`, `_author_identity`; `record_is_readable`; `RecordsStore.read_entry`) and `knowledge/semantic.py` (`index_record`; the anonymous reader's clauses in `build_records_scope_filter`); one new test file; two existing test files updated with inline reasons.
- *G1 (the label).* An unrecognised value is anything that is not exactly one of the four label strings, with no case-folding. It reads as private, with the reader-identity rules, as `security/classification.py` already reads an unknown source label. A missing key stays `ship`. One public helper serves the three readers and the index, so the copies cannot drift apart again. Rejected:
  - patching each reader in place (three copies, which is how the paths came to disagree);
  - `read_entry` calling `record_is_readable` (it would also change `read_entry`'s documented department rule);
  - a `$nin` clause in the filter (dead code behind the index's normalisation, and it could only loosen).

  This amends limit L3 of the frontmatter-framing work (#1686) for its unrecognised half only.
- *G2 (the author).* An author that is empty or not a string equals no reader id, as the stand-in for an unparsed frontmatter already makes it. The anonymous reader gets no author clause in the filter. Deferred: refusing an empty author in `write_entry`, which would not reach a hand-made note.
- *Residual.* L1 to L6 of the contract. *Reversal.* Revert the batch's commits in reverse order; no stored data changes.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. No AD or BF number moves. The roadmap Bug Tracker is not edited.

## 5. Commit messages

Every body ends with its `Refs` paragraph, and the committing agent's trailer paragraph comes after it. No subject contains an `AD-` or `BF-` token or this file's name. No message uses a closing keyword in any form: close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved. Do not write "fail closed" or "fixed-length"; write "refuses", "is denied" or "private by default".

| Commit | Subject | Body |
|---|---|---|
| Contract (the orchestrator's) | `Records reader gates (#1797, #1800): contract for an unrecognised classification read as private and an authorless note refused to the anonymous reader` | `Refs #1797, #1800.` |
| M1 | `Records reader gates M1: tests for unrecognised classifications and authorless notes, xfail until built (#1797, #1800)` | `Refs #1797, #1800.` |
| M2a | `Records reader gates M2a: a classification that is not one of the four labels is read as private on every reader path (#1797)` | `Refs #1797.` |
| M2b | `Records reader gates M2b: a note with no author admits no reader by authorship, the anonymous reader included (#1800)` | `Refs #1800.` |
| M3 | `Records reader gates M3: trackers and ledger (#1797, #1800)` | `Refs #1797, #1800.` |

Checked by hand against both scans: no subject above holds `clos`, `fix` or `resolv`.

With `BASE` = the `origin/main` commit the batch is built on, both scans must print nothing:
- `git log --format=%B BASE..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B BASE..HEAD | rg -n -i "\b(clos[e][sd]?|fix(e[sd])?|resolv[e][sd]?)\b"`

The orchestrator closes both issues after the gate.

## 6. Recorded limits

- **L1 (#1797).** `write_entry`'s own check (`records_store.py:791`) still raises `TypeError`, not `ValueError`, for an unhashable programmatic value. Every caller in `src` passes a literal, a constant or a configured string (section 11).
- **L2 (#1797).** The backlinks graph still shows the raw label (`backlinks.py:369`). `diagnostic_context.py:386-401` still lists metadata of notes `read_entry` refuses (AD-661f). No migration: a hand-edited file is the Captain's to correct. A list- or dict-valued note was never indexed, so it is still pending and the next backfill indexes it; an already indexed record is not re-indexed (L4 of the framing work).
- **L3 (#1797).** The AD-1157a carry-forward (`records_store.py:839-842`) stays a membership test, so an odd stored label is replaced by the caller's default, not by private.
- **L4 (#1800).** An author of only blanks (`" "`) is still an author. Only an empty or non-`str` author is nobody.
- **L5 (#1800).** A department note with no `department` frontmatter is still returned by `read_entry` to a reader that has no department, where `record_is_readable` and search refuse it (`records_store.py:165-172`, unchanged).
- **L6 (both).** The archive promotion reads as `""` (`archive_promotion.py:68`). It is now refused an odd-labelled note and an authorless private or department note. Both were already withheld from the archive (`archive_store.py:93`, ship and fleet only), and the refusal path is the one any private note takes (`archive_promotion.py:315-321`, `:372-375`).

## 7. Mutation rows (each line occurs once, stripped, in its file after M2b; expected, not measured)

| # | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | records_store | `if doc_class not in _IDENTITY_GATED_CLASSIFICATIONS:` | `if doc_class not in _IDENTITY_GATED_CLASSIFICATIONS or doc_class != frontmatter.get("classification", "ship"):` (issue M1) | matrix (search, predicate); parity; `..._is_private_and_identity_gated` |
| 2 | same | `doc_class = effective_classification(gate.get("classification", "ship"))` | `doc_class = gate.get("classification", "ship")` (issue M2) | matrix (read_entry) |
| 3 | same | `if type(value) is str and value in _CLASSIFICATION_LEVELS:` | that line with `value.lower() in`, then `return value.lower()` as its body (issue M3) | matrix `upper-ship` |
| 4 | same | same | `if value in _CLASSIFICATION_LEVELS:` (issue M4) | matrix list-private, list-ship, mapping; index (both) |
| 5 | same | `doc_class = effective_classification(frontmatter.get("classification", "ship"))` | `... frontmatter.get("classification"))` (issue M5) | labels `missing-key`; `test_missing_classification_defaults_to_ship` |
| 6 | same | `doc_class = effective_classification(gate.get("classification", "ship"))` | `... gate.get("classification"))` | labels `missing-key` (read_entry) |
| 7 | semantic | `effective = effective_classification(classification)` | `effective = classification if classification in _CLASSIFICATION_LEVELS else "private"` (issue M6) | index (both); parity premise |
| 8 | records_store | `return "private"` | `return "department"` (issue M7) | matrix (all ten: carol) |
| 9 | same | `if type(value) is str and value in _CLASSIFICATION_LEVELS:` | the line `if value is None: return "ship"` inserted above it (issue M8) | matrix `null` |
| 10 | same | `return "private"` | `return "fleet"` | none-reader (scope private); matrix |
| 11 | semantic | `if effective != classification:` | `if False:` | index (the WARNING) |
| 12 | records_store | `doc_author = _author_identity(frontmatter.get("author"))` | `doc_author = frontmatter.get("author", "")` (#1800's named mutation) | authorless (search, predicate) |
| 13 | same | `doc_author = _author_identity(gate.get("author"))  # BF-969 (#1800): an empty or non-str author is nobody` | `doc_author = gate.get("author", "")` | authorless (read_entry) |
| 14 | same | `if type(value) is str and value:` | `if type(value) is str:` | authorless (all three) |
| 15 | semantic | `if gated_labels and reader_id:` | `if gated_labels:` | `..._is_given_the_open_labels_only`; `..._at_private_scope_admits_nothing`; parity (reader "") |

## 8. What this does NOT change

- **Source:**
  - `write_entry` and its validation;
  - the AD-1157a carry-forward;
  - `_unparsed_gate`;
  - `read_entry`'s department rule and its Captain bypass;
  - `search`'s scope validation (`records_store.py:1740`);
  - `reindex_records` (`semantic.py:756-771`, a caller only);
  - the stored author (`semantic.py:434`, `:760`);
  - `backlinks.py`, `diagnostic_context.py` and `archive_promotion.py`.
- **Config:** no key and no model.
- **Elsewhere:**
  - `ui/` and the commercial overlay;
  - every tracker except `PROGRESS.md`, `DECISIONS.md` and the ledger pair;
  - the roadmap Bug Tracker.

## 9. Diff Reviewer (`gpt-6.1-sol`): properties to verify

Name the consumer for each property and confirm that it accepts the change.

1. **The label.** For every value, `effective_classification` returns one of the four labels and never raises. It returns the value exactly when it is a `str` equal to a label.
   - **Consumers:** `record_is_readable` (`records_store.py:127`), `read_entry`, and `index_record` (via the import at `semantic.py:20-25`).
2. **The keyword paths.** A note with an unrecognised label is admitted only to `None`, `"captain"` and its author (subject to scope level 0). The search still returns nothing `read_entry` withholds (the framing work's L11, BF-952 A5).
   - **Consumers:** `_base_reading_admits` (`records_store.py:399-423`) and the scan at `:515-521`.
3. **The author.** An author that is empty or not a `str` admits no reader by authorship on all three paths. `None`, the Captain and the department clause are unchanged.
   - **Consumers:**
     - `SemanticKnowledgeLayer.search` skips a `None` filter (`semantic.py:518-528`);
     - the archive reader `""` (`archive_promotion.py:68`, `:315-321`, `:372-375`);
     - the route `GET /api/records/documents/{path}` (`routers/records.py:102`, `:136`).
4. **The index.** It stores only the four labels and WARNs when the stored label differs from the input. It does not raise on a classification.
   - **Consumers:** `reindex_records` (`semantic.py:756-771`) and `build_records_scope_filter`.
5. **The tests.**
   - No assertion is loosened, and each changed existing case states its reason inline.
   - The parity test asserts its premise first.
   - The new file's xfail cases fail at their own `assert` on the base.
   - The census files of G2 are unedited and green.
6. **Paperwork.** The text is ASCII. The tracker lines and subjects carry no `AD-` or `BF-` token.

## 10. Acceptance criteria

- **#1797:**
  - The ten unrecognised values admit alice and the Captain, and refuse bob, carol and `""`, through `read_entry`, `search(scope="ship")` and `record_is_readable(scope="ship")`. The premise is asserted first.
  - `reader_id=None` reads such a note at every scope and finds it by search.
  - The four labels and a missing key read as before.
  - `index_record` with a list or a mapping does not raise, indexes as private and WARNs.
  - Parity holds after a backfill.
  - Rows 1 to 11 each fail a named test.
- **#1800:**
  - The three authorless notes are refused to `""` on all three paths and still returned to the Captain.
  - The department note is still read by its department.
  - Parity holds for `""`.
  - Row 12 fails the authorless test.
  - `test_bf679...:527-549` change with reasons inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 11. Verified Against Codebase (2026-11-14, worktree `next-read2` at `5275d00874799d68536fef2a7ff27c7bc44cda65`)

```
grep -n "_CLASSIFICATION_LEVELS = \|def record_is_readable\|def _unparsed_gate\|FRONTMATTER_UNPARSED_KEY = " records_store.py
  71, 127, 113, 110
records_store.py:174-196 (body), :1498-1537 (read_entry), :735-742 (write_entry, classification="ship"), :791, :812, :839-842
records_store.py:1035-1036: write_notebook refuses an empty callsign
semantic.py:20-25 (imports), :40-128 (filter), :113 "    if gated_labels:", :395-401, :427-442, :751-771
security/classification.py:123: "source unknown -> most restrictive (private=0)"
config/ontology/records.yaml:146-148: values [private, department, ship, fleet]
prompts/bf-940-frontmatter-closing-line.md:140, :1174: "**L3"
archive_promotion.py:68 ARCHIVE_READER = ""; archive_store.py:93 PROMOTABLE_CLASSIFICATIONS = {"ship", "fleet"}
routers/records.py:102 reader: str = "captain"; :136 read_entry(path, reader_id=reader)
tests: test_bf679...:527-550, :630-639, :234-251; test_bf940_frontmatter_framing.py:293, :317; test_ad1138...:378-387
```

**The consumer search (run 2026-11-14):**
- `rg "record_is_readable|build_records_scope_filter|_CLASSIFICATION_LEVELS|effective_classification|index_record|_IDENTITY_GATED_CLASSIFICATIONS" tests -c` found 9 files: `fixtures/ad1346_store_family_census.py` (`:155` row for `SemanticKnowledgeLayer.index_record`; it counts ChromaDB writes, and this batch adds none), `test_ad1138`, `test_ad1140`, `test_ad1157`, `test_ad1179_vocabulary_constants`, `test_bf679`, `test_bf684`, `test_bf940_s2_writer_policy` and `test_bf940_s4`. All are in G2 except `test_bf940_s2` (an `index_record` mention only).
- `rg "records_store\.py|knowledge/semantic\.py|index_record\b" tests` found the censuses `fixtures/ad1346_effect_census.py:143` (`_git_sync`), `fixtures/ad1346_file_write_census.py:146` (`write_entry` and its `author` parameter, unchanged), `test_layer_boundaries.py:88,92`, `test_bf892_spawn_env_guard.py:101` (`_git_sync`) and `test_records_store.py:423` (the `def` name duplicate scan: `effective_classification` and `_author_identity` are absent from `src`, below).
- `scripts/check_architecture_principles.py` reaches `records_store` only through baseline row `architecture-baseline.yaml:751` (srp-size of the `RecordsStore` class, by triggers). The new functions are module-level.
- `rg "(dir|vars|getmembers)\((records_store|semantic)" tests` found no census of either module's public names.
- Odd labels pinned to readers: `rg "classification...: ...(top-secret|bogus|...|SHIP)" tests` and the negated-label scan found `test_bf679:633` (edited), `test_ad1157:330` (carry-forward, unchanged), `test_ad1138:381` (index, unchanged), `test_ad1341_s1_archive_store.py:203` (the archive's own check) and `test_bf940_frontmatter_framing.py:293` (edited).

**Absence verified (2026-11-14):**
- CLAIM: `effective_classification` and `_author_identity` exist nowhere in `src`. RUN: `rg "effective_classification|_author_identity" src`. FOUND: none. HOLDS: yes.
- CLAIM: no `src` call passes a literal `reader_id=""`. RUN: `rg 'read_entry\([^)]*""|reader_id=""|reader=""' src`. FOUND: none. HOLDS: yes. The `""` arrives by value instead, through:
  - `ARCHIVE_READER = ""`, read at `archive_promotion.py:315` and `:372`;
  - the route's query parameter (`routers/records.py:102`, `:136`);
  - the Oracle's anonymous reader (`oracle_service.py:667`, `:1061`, `:1074`, `:1099`, `:1145` forward `reader_id`; anonymous `""` per `test_bf679` `TestResolveRecordsReader:751`).
  - `cognitive_agent.py:8717`, `dm_targeted_lookup.py:251` and `recreation/history.py:198` forward a variable, not traced.
  - Tests: `test_ad1341_s5_after_action.py:109`, `:277`, `:287` and `test_ad1341_s5_continuous_promotion.py:246`, `:304`, `:337` read ship notes as `""`, which is unaffected.
- CLAIM: the writers that can leave an author empty on an identity-gated note. RUN: `rg -A9 "\.write_entry\(" src` (16 sites).
  - 13 sites pass `"system"`, `"shipyard"` or a callsign with `classification="ship"`, which is not identity-gated: `after_action.py:372`, `peer_perception.py:350`, `avatars/records_writer.py:168`, `commands_gap.py:244`, `records_store.py:947`, `dreaming.py:1145`, `:1372`, `proactive.py:4021`, `recreation/service.py:377`, `stand_down.py:328`, `routers/gaps.py:186`, `procedure_store.py:719`, `:1729`.
  - Three sites can write a gated note: `creative/output_writer.py:105` (`author_callsign`, configurable classification, no empty check at this layer), `records_store.py:1039` (`write_notebook`, which refuses an empty callsign at `:1035`), and `dreaming.py:1012` (it carries the primary note's `author`, `""` included; its classification takes the default `ship`).
  - Beyond these: a hand-made or hand-edited file, and a note without the key. `routers/records.py:205` calls `write_notebook`.
  - HOLDS: yes.
- CLAIM: `tests/test_bf966_*` does not exist. RUN: Glob `tests/test_bf96[69]*`. FOUND: none.

## 12. Prior Art and Blind Spots

- **Prior art.** This is a bug fix to an access control, so the external search is skipped under the drafting standard. The internal precedent is `security/classification.py:123` (an unknown source label is most restrictive) and `_unparsed_gate` (`records_store.py:113-124`, `None` as nobody's author). Both are adopted.
- **Blind spots and what was decided:**
  - The archive reader `""` is now refused the same notes: they were withheld anyway (L6).
  - Case variants are not folded, by the Captain's decision. A folding helper would admit `SHIP` to every reader.
  - `semantic.search` already skips a `None` filter, so `""` at private scope costs nothing.
  - `dreaming.py:1012` rewrites a consolidated note at the default `ship` classification. This is out of scope and its reachability is not verified; see the note to the orchestrator.
