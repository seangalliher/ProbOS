"""BF-940 slice 4 (#1686, L19): a document whose frontmatter does not load is private to the owner of its notebook directory.

YAML refused the frontmatter of such a document (broken YAML, or the ``!!python/tuple`` tag an older ``write_entry`` wrote), so every
reader read it as ``{}``, the default ``ship`` classification: ``read_entry`` and the keyword search handed it to every reader, the
semantic backfill indexed it as ``ship`` and a Captain's ``publish`` rewrote it with a status and a time only. Real ``RecordsStore``
over ``tmp_path`` with ``~`` moved and hand-made documents; the backfill runs against the one collection method it uses, not ChromaDB.

The class is strict xfail until M2 (each case fails at an ``assert`` of its own body on the unfixed tree, after its premise); the
module's functions are guards and pass on both trees: they hold what this slice must not change (a document with no frontmatter, an
empty one or an unclosed opener; a frontmatter the base's cut reads; a constructor error; the scans; the parse and the mapping
``read_entry`` returns; an update-in-place, which ``seed_manuals`` runs at every boot). A case asserts its premise first (YAML refuses
the block, the Captain reads the document, a healthy private note is refused to bob), so "bob is refused" cannot mean the store was
broken.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer

_KEY = "frontmatter_unparsed"
_BODY = "private warp body"
_BROKEN = "author: alice\nclassification: private\nstatus: draft\nbroken: [unclosed\n"
_TAGGED = "author: alice\nclassification: private\nstatus: draft\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n"
_TABBED = "author:\talice\nclassification:\tprivate\n"
_REFUSED = [
    pytest.param(_BROKEN, id="broken-yaml"),
    pytest.param(_TAGGED, id="python-tag"),
]
_PLACES = [
    pytest.param("notebooks/alice/note.md", True, id="alices-notebook"),
    pytest.param("reports/note.md", False, id="a-report"),
]
_NOT_A_PARSE_FAILURE = [
    pytest.param("warp plain body\n", id="no-frontmatter"),
    pytest.param("---\n---\n\nwarp empty body\n", id="an-empty-frontmatter"),
    pytest.param("---\n[]\n---\n\nwarp falsy body\n", id="a-falsy-frontmatter"),
    pytest.param("---\n# a comment only\n---\n\nwarp comment body\n", id="a-comment-only-frontmatter"),
    pytest.param("---\nauthor: alice\nclassification: private\nwarp never closed body\n", id="an-opener-with-no-closing-line"),
]


class _Collection:
    """The one method the records index uses of a ChromaDB collection, and the lookup the backfill makes."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, Any]]] = {}

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        self.rows[ids[0]] = (documents[0], metadatas[0])

    def get(self, ids: list[str], include: Any = None) -> dict[str, list[str]]:
        return {"ids": [i for i in ids if i in self.rows]}


def _make_store(root: Path) -> RecordsStore:
    root.mkdir(parents=True, exist_ok=True)
    return RecordsStore(RecordsConfig(repo_path=str(root), auto_commit=False))


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordsStore:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    return _make_store(tmp_path / "ship-records")


def _raw(block: str, body: str = _BODY) -> str:
    return f"---\n{block}---\n\n{body}\n"


def _hand_made(store: RecordsStore, path: str, text: str) -> None:
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _healthy(store: RecordsStore, path: str, body: str, **frontmatter: Any) -> None:
    values = {"author": "captain", "classification": "ship", "status": "published", **frontmatter}
    _hand_made(store, path, f"---\n{yaml.safe_dump(values, sort_keys=False)}---\n\n{body}\n")


async def _found(store: RecordsStore, reader_id: str | None, query: str = "warp") -> list[str]:
    return [hit["path"] for hit in await store.search(query, scope="ship", reader_id=reader_id)]


async def _attempt(call: Any) -> tuple[type | None, str]:
    try:
        await call
    except Exception as exc:  # noqa: BLE001 -- the case asserts on the type and the text
        return type(exc), str(exc)
    return None, ""


async def _premise(store: RecordsStore, path: str, block: str) -> None:
    """YAML refuses the block; the Captain reads the document as ``{}`` with its body; a healthy private note is refused to bob."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(block)
    _hand_made(store, path, _raw(block))
    control = "notebooks/alice/control.md"
    _healthy(store, control, "control body", author="alice", classification="private")
    assert await store.read_entry(control, reader_id="bob") is None, "premise: the gate refuses a private note"
    assert await store.read_entry(control, reader_id="alice") is not None, "premise: its author reads it"
    assert await store.read_entry(path, reader_id="captain") == {"frontmatter": {}, "content": _BODY, "path": path}, "premise: {}"


async def test_a_document_that_loads_is_read_listed_and_published_as_before(store):
    private, shared = "notebooks/alice/private.md", "reports/open.md"
    _healthy(store, private, "private warp", author="alice", classification="private")
    _healthy(store, shared, "open warp")
    assert await store.read_entry(private, reader_id="bob") is None
    own = await store.read_entry(private, reader_id="alice")
    assert own is not None and set(own) == {"frontmatter", "content", "path"}
    assert sorted(await _found(store, "alice")) == [private, shared] and await _found(store, "bob") == [shared]
    assert all(set(entry) == {"path", "frontmatter"} for entry in await store.list_entries())
    await store.publish(private, "alice")
    published = await store.read_entry(private, reader_id="alice")
    assert published is not None and published["frontmatter"]["status"] == "published" and published["frontmatter"]["author"] == "alice"


@pytest.mark.parametrize("text", _NOT_A_PARSE_FAILURE)
async def test_a_document_with_nothing_to_load_is_not_a_parse_failure(store, text):
    path = "notebooks/alice/note.md"
    _hand_made(store, path, text)
    assert await store.read_entry(path, reader_id="captain") is not None, "premise: the Captain reads it"
    assert await store.read_entry(path, reader_id="bob") is not None
    assert path in await _found(store, "bob")
    listed = [entry for entry in await store.list_entries() if entry["path"] == path]
    assert len(listed) == 1 and _KEY not in listed[0]


@pytest.mark.parametrize("classification", ["private", "ship"])
async def test_a_frontmatter_that_loads_through_the_base_cut_is_not_a_parse_failure(store, classification):
    path = "notebooks/alice/review---nominal.md"
    block = f"author: alice\nclassification: {classification}\nstatus: draft\ntopic: review---nominal\nmetrics:\n  sample: !!python/tuple\n  - 1\n  - 2\n"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(block)
    _hand_made(store, path, _raw(block, "coolant private body"))
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"]["classification"] == classification, "premise: the cut reads it as alice's note"
    shown = classification == "ship"
    assert (await store.read_entry(path, reader_id="bob") is not None) == shown
    assert (path in await _found(store, "bob", "coolant")) == shown
    assert [e for e in await store.list_entries() if e["path"] == path] == [{"path": path, "frontmatter": own["frontmatter"]}]


async def test_a_constructor_error_is_refused_to_every_reader_as_before(store):
    path = "notebooks/alice/dated.md"
    with pytest.raises(ValueError):
        yaml.safe_load("updated: 2026-13-05\n")  # premise: a constructor error, which is not a YAMLError
    _hand_made(store, path, _raw("author: alice\nclassification: private\nupdated: 2026-13-05\n"))
    for reader in ("alice", "bob", "captain"):
        assert (await _attempt(store.read_entry(path, reader_id=reader)))[0] is ValueError, reader
        assert await _found(store, reader) == [], reader
    assert await store.list_entries() == []
    assert (await _attempt(store.publish(path, "captain")))[0] is ValueError


async def test_the_scans_skip_a_document_whose_frontmatter_does_not_load(store):
    words = "warp core coolant alpha beta gamma delta epsilon zeta eta theta"
    await store.write_notebook("alice", "other", words, department="dept_a")
    await store.write_notebook("carol", "n2", words, department="dept_c")
    assert (await store.check_notebook_similarity("alice", "newslug", words))["action"] == "suppress", "premise: a healthy note answers"
    matches = (await store.check_cross_agent_convergence("bob", "dept_b", "warp", words))["convergence_matches"]
    assert sorted(m["callsign"] for m in matches) == ["alice", "carol"], "premise: healthy notes converge"
    _hand_made(store, "notebooks/alice/other.md", _raw(_BROKEN, words))
    assert (await store.check_notebook_similarity("alice", "newslug", words))["action"] == "write"
    matches = (await store.check_cross_agent_convergence("bob", "dept_b", "warp", words))["convergence_matches"]
    assert sorted(m["callsign"] for m in matches) == ["carol"]


async def test_an_update_in_place_of_such_a_note_proceeds_and_seed_manuals_re_seeds_a_broken_manual(store, tmp_path):
    path = "notebooks/alice/nb.md"
    _hand_made(store, path, _raw(_TAGGED))
    assert await store.write_notebook("alice", "nb", "replacement body") == path
    again = await store.read_entry(path, reader_id="alice")
    assert again is not None and again["content"] == "replacement body"
    assert again["frontmatter"]["author"] == "alice" and again["frontmatter"]["classification"] == "private"
    source = tmp_path / "manuals"
    source.mkdir()
    (source / "m.md").write_text("# Manual\n\nmanual warp body\n", encoding="utf-8")
    _hand_made(store, "manuals/m.md", _raw(_BROKEN, "old"))
    assert await store.seed_manuals(source) == 1
    seeded = await store.read_entry("manuals/m.md", reader_id="bob")
    assert seeded is not None and seeded["frontmatter"]["author"] == "shipyard" and "manual warp body" in seeded["content"]


@pytest.mark.parametrize("block", _REFUSED)
def test_the_parse_of_such_a_document_is_what_it_always_was(store, block):
    assert store._parse_document(_raw(block)) == ({}, _BODY)


@pytest.mark.parametrize("block", _REFUSED)
async def test_read_entry_returns_the_mapping_it_always_returned_to_the_captain(store, block):
    path = "notebooks/alice/note.md"
    _hand_made(store, path, _raw(block))
    assert await store.read_entry(path, reader_id="captain") == {"frontmatter": {}, "content": _BODY, "path": path}


async def test_the_owner_of_a_notebook_directory_reads_such_a_document_at_any_depth(store):
    for path in ("notebooks/alice/note.md", "notebooks/alice/sub/deeper/note.md"):
        _hand_made(store, path, _raw(_BROKEN))
        assert await store.read_entry(path, reader_id="alice") is not None, path
        assert path in await _found(store, "alice"), path


@pytest.mark.xfail(reason="BF-940 slice 4 M2: not built", raises=AssertionError, strict=True)
class TestADocumentWhoseFrontmatterDoesNotLoadIsPrivateToItsOwner:
    @pytest.mark.parametrize("block", _REFUSED)
    @pytest.mark.parametrize(("path", "owned"), _PLACES)
    async def test_read_entry_gives_it_to_the_captain_and_the_owner_only(self, store, block, path, owned):
        await _premise(store, path, block)
        for reader, shown in {"alice": owned, "bob": False, "captain": True, "": False, "system": False}.items():
            entry = await store.read_entry(path, reader_id=reader)
            assert (entry is not None) == shown, reader
            assert entry is None or entry == {"frontmatter": {}, "content": _BODY, "path": path}, reader

    @pytest.mark.parametrize("block", _REFUSED)
    @pytest.mark.parametrize(("path", "owned"), _PLACES)
    async def test_the_keyword_search_finds_it_for_the_captain_the_owner_and_an_identity_less_search_only(
        self, store, block, path, owned,
    ):
        await _premise(store, path, block)
        for reader, shown in {"alice": owned, "bob": False, "captain": True, None: True, "": False}.items():
            assert (path in await _found(store, reader)) == shown, reader

    async def test_a_document_withheld_from_a_reader_does_not_move_the_scores_that_reader_is_shown(self, store, tmp_path):
        plain = _make_store(tmp_path / "plain")
        for target in (store, plain):
            _healthy(target, "reports/h1.md", "warp")
            _healthy(target, "reports/h2.md", "coolant")
        _hand_made(store, "notebooks/alice/u.md", _raw(_BROKEN, "warp"))

        async def scores(target: RecordsStore, reader: str) -> dict[str, float]:
            return {hit["path"]: hit["score"] for hit in await target.search("warp coolant", scope="ship", reader_id=reader)}

        expected = await scores(plain, "bob")
        assert set(expected) == {"reports/h1.md", "reports/h2.md"}, "premise: the healthy documents are found"
        assert await scores(store, "captain") != await scores(plain, "captain"), "premise: a document a reader may read moves the scores"
        assert await scores(store, "bob") == expected

    @pytest.mark.parametrize("block", [
        pytest.param(_BROKEN, id="broken-yaml"),
        pytest.param(_TAGGED, id="python-tag"),
        pytest.param(_TABBED, id="tab-after-key"),
    ])
    async def test_the_listing_marks_the_entry_of_such_a_document_and_no_other(self, store, block):
        path = "notebooks/alice/note.md"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(block)
        _hand_made(store, path, _raw(block))
        _healthy(store, "reports/ok.md", "healthy body")
        entries = {entry["path"]: entry for entry in await store.list_entries()}
        assert set(entries) == {path, "reports/ok.md"}, "premise: the listing holds both"
        assert _KEY not in entries["reports/ok.md"], "premise: a document that loads has no key"
        assert entries[path] == {"path": path, "frontmatter": {}, _KEY: True}

    async def test_the_semantic_backfill_leaves_such_a_document_out_and_names_it(self, store, tmp_path, caplog):
        column = _Collection()
        layer = SemanticKnowledgeLayer(tmp_path / "semantic")
        layer._collections = {"records": column}
        _healthy(store, "reports/open.md", "open warp")
        _healthy(store, "notebooks/alice/private.md", "private warp", author="alice", classification="private")
        legacy = [f"notebooks/alice/legacy-{n}.md" for n in range(7)]
        for path in legacy:
            _hand_made(store, path, _raw(_TAGGED, "legacy warp body"))
        with caplog.at_level(logging.WARNING, logger="probos.knowledge.semantic"):
            indexed = await layer.reindex_records(store)
        assert indexed == 2 and sorted(column.rows) == ["record_notebooks/alice/private.md", "record_reports/open.md"]
        assert column.rows["record_notebooks/alice/private.md"][1]["classification"] == "private"
        logged = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(logged) == 1 and "7 record(s)" in logged[0] and "legacy warp body" not in logged[0]
        assert all(path in logged[0] for path in legacy[:5]) and not any(path in logged[0] for path in legacy[5:])

    @pytest.mark.parametrize("who", ["captain", "alice", "bob"])
    async def test_publish_refuses_such_a_document_for_everyone_and_writes_nothing(self, store, who):
        path = "notebooks/alice/note.md"
        _hand_made(store, path, _raw(_TAGGED))
        before = (store.repo_path / path).read_bytes()
        kind, message = await _attempt(store.publish(path, who))
        assert kind is ValueError and path in message, (kind, message)
        assert _BODY not in message
        assert (store.repo_path / path).read_bytes() == before

    async def test_an_update_in_place_of_such_a_note_logs_its_path_and_proceeds(self, store, caplog):
        path = "notebooks/alice/nb.md"
        _hand_made(store, path, _raw(_TAGGED))
        with caplog.at_level(logging.WARNING, logger="probos.knowledge.records_store"):
            assert await store.write_notebook("alice", "nb", "replacement body") == path
        warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warned) == 1 and path in warned[0] and "replacement body" not in warned[0] and _BODY not in warned[0]
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["content"] == "replacement body"

    async def test_a_legacy_private_note_stays_private_through_the_readers_the_index_and_its_owners_repair(self, store, tmp_path):
        column = _Collection()
        layer = SemanticKnowledgeLayer(tmp_path / "semantic")
        layer._collections = {"records": column}
        legacy, shared = "notebooks/alice/legacy.md", "reports/open.md"
        _healthy(store, shared, "open warp")
        _hand_made(store, legacy, _raw(_TAGGED, "legacy warp body"))
        assert legacy in await _found(store, "alice") and legacy in await _found(store, "captain"), "premise: its owner and the Captain find it"
        assert await store.read_entry(legacy, reader_id="bob") is None
        assert await _found(store, "bob") == [shared]
        assert await layer.reindex_records(store) == 1 and sorted(column.rows) == [f"record_{shared}"]
        assert await store.write_notebook("alice", "legacy", "repaired warp body") == legacy
        assert await store.read_entry(legacy, reader_id="bob") is None and await _found(store, "bob") == [shared]
        mine = await store.read_entry(legacy, reader_id="alice")
        assert mine is not None and mine["frontmatter"]["classification"] == "private" and legacy in await _found(store, "alice")
        assert await layer.reindex_records(store) == 1
        metadata = column.rows[f"record_{legacy}"][1]
        assert metadata["classification"] == "private" and metadata["author"] == "alice"

    @pytest.mark.parametrize(("path", "reader"), [
        pytest.param("notebooks/alice2/note.md", "alice", id="a-callsign-that-is-a-prefix-is-not-the-owner"),
        pytest.param("notebooks/loose.md", "loose.md", id="a-file-straight-under-notebooks-has-no-owner"),
        pytest.param("reports/alice/note.md", "alice", id="only-a-notebook-directory-names-an-owner"),
        pytest.param("notebooks/bob/note.md", "alice", id="another-callsigns-notebook"),
    ])
    async def test_nobody_else_is_the_owner_of_such_a_document(self, store, path, reader):
        _hand_made(store, path, _raw(_BROKEN))
        assert await store.read_entry(path, reader_id="captain") is not None, "premise: the Captain reads it"
        assert await store.read_entry(path, reader_id=reader) is None
        assert path not in await _found(store, reader)

    async def test_the_owner_is_taken_from_the_resolved_path_not_from_its_spelling(self, store):
        (store.repo_path / "notebooks" / "alice").mkdir(parents=True)
        _hand_made(store, "notebooks/bob/note.md", _raw(_BROKEN))
        spelled = "notebooks/alice/../bob/note.md"
        assert await store.read_entry(spelled, reader_id="captain") is not None, "premise: the spelling reaches the document"
        assert await store.read_entry(spelled, reader_id="bob") is not None
        assert await store.read_entry(spelled, reader_id="alice") is None

    async def test_a_note_only_libyaml_reads_is_withheld_by_the_search_where_read_entry_withholds_it(self, store):
        path = "notebooks/alice/tabbed.md"
        block = "author:\talice\nclassification:\tship\n"
        with pytest.raises(yaml.YAMLError):
            yaml.safe_load(block)
        _hand_made(store, path, _raw(block))
        assert await store.read_entry(path, reader_id="bob") is None
        assert path not in await _found(store, "bob")
        assert path in await _found(store, "alice") and path in await _found(store, "captain")
