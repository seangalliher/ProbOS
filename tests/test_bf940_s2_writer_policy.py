"""BF-940 slice 2 (#1686): a frontmatter the store writes is one the store reads (L24), and a numeric tag reaches the index (L27).

Real ``RecordsStore`` over ``tmp_path`` with ``~`` moved, no network. The two classes are strict xfail until M2 (each case fails
at an ``assert`` of its own body on the unfixed tree, after its premise); the module's functions are guards and pass on both
trees. A privacy case is one note in a fresh store and asserts first that the author's own search finds it, so "bob does not
find it" cannot mean the search found nothing at all.
"""

from __future__ import annotations

import collections
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.skill_catalog import CognitiveSkillCatalog, parse_skill_file
from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.routers.records import router


class _Plain:
    pass


class _Text(str):
    pass


class _Pair(NamedTuple):
    a: int
    b: int


class _Collection:
    """The one method the records index uses of a ChromaDB collection, and the lookup the backfill makes."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, dict[str, Any]]] = {}

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        self.rows[ids[0]] = (documents[0], metadatas[0])

    def get(self, ids: list[str], include: Any = None) -> dict[str, list[str]]:
        return {"ids": [i for i in ids if i in self.rows]}


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordsStore:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    (tmp_path / "ship-records").mkdir()
    return RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))


async def _hits(store: RecordsStore, reader: str) -> list[str]:
    return [hit.get("path", "") for hit in await store.search("coolant", reader_id=reader)]


def _hand_made(store: RecordsStore, path: str, text: str) -> None:
    (store.repo_path / path).parent.mkdir(parents=True, exist_ok=True)
    (store.repo_path / path).write_text(text, encoding="utf-8")


def _app(store: RecordsStore) -> FastAPI:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(config=SystemConfig(), records_store=store, _records_store=store)
    app.include_router(router)
    return app


@pytest.mark.parametrize("sample", [
    pytest.param([1, 2], id="a-list"),
    pytest.param({1, 2}, id="a-set"),
    pytest.param(float("nan"), id="nan"),
])
async def test_a_value_the_readers_load_keeps_a_private_note_private(store, sample):
    """Guard: the list control of case B, and the two values ``yaml.dump`` writes without a tag."""
    path = await store.write_notebook("alice", "review-nominal", "coolant private body", metrics={"sample": sample})
    assert path in await _hits(store, "alice"), "premise: the author finds her own note"
    assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
    assert await store.read_entry(path, reader_id="bob") is None and path not in await _hits(store, "bob")
    await store.publish(path, "alice")
    assert await store.read_entry(path, reader_id="bob") is None


async def test_the_bytes_written_for_values_the_readers_load_are_what_yaml_dump_wrote(store):
    """Guard: the writer's text for native values is ``yaml.dump``'s, byte for byte (a ``safe_dump`` must not change a file)."""
    path = await store.write_notebook(
        "alice", "native", "body", department="science", tags=["a", "717", "x --- y"],
        metrics={"trust_mean": 0.512, "n": 3, "ok": True, "none": None, "nested": {"k": [1, {"j": "v"}]}},
        extra_frontmatter={"env": {"note": "caf\u00e9 \u2014 line1\nline2", "when": "2026-11-09"}},
    )
    raw = (store.repo_path / path).read_text(encoding="utf-8")
    block = raw[4:raw.index("\n---\n\n") + 1]
    loaded = yaml.safe_load(block)
    assert loaded["tags"] == ["a", "717", "x --- y"] and loaded["metrics"]["nested"] == {"k": [1, {"j": "v"}]}
    assert block == yaml.dump(loaded, default_flow_style=False, sort_keys=False)


async def test_the_captains_log_is_written_and_read_as_before(store):
    path = await store.append_captains_log("log body", "m")
    entry = await store.read_entry(path, reader_id="bob")
    assert entry is not None and entry["frontmatter"]["author"] == "captain"
    assert entry["frontmatter"]["classification"] == "ship"


async def test_a_publish_of_a_note_holding_a_set_bytes_and_a_date_keeps_it_readable(store):
    """Guard: values ``safe_load`` builds and ``yaml.dump`` writes without a tag stay as they were through ``publish``."""
    path = "notebooks/alice/typed.md"
    _hand_made(store, path, "---\nauthor: alice\nclassification: private\nkinds: !!set {p, q}\nraw: !!binary aGk=\nwhen: 2026-01-01\n---\n\ncoolant private body\n")
    assert path in await _hits(store, "alice"), "premise: the author finds her own note"
    await store.publish(path, "alice")
    assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"]["kinds"] == {"p", "q"} and own["frontmatter"]["raw"] == b"hi"
    assert await store.read_entry(path, reader_id="bob") is None


@pytest.mark.parametrize(("tags", "written"), [
    pytest.param(None, False, id="none"),
    pytest.param([], False, id="an-empty-list"),
    pytest.param("", False, id="an-empty-string"),
    pytest.param(["a", "b"], True, id="a-list-of-text"),
])
async def test_tags_that_are_absent_empty_or_text_are_written_as_before(store, tags, written):
    path = await store.write_notebook("alice", "tagged", "coolant body", tags=tags)
    entry = await store.read_entry(path, reader_id="alice")
    assert entry is not None and ("tags" in entry["frontmatter"]) is written


def test_the_notebook_route_writes_a_list_of_tags_as_before(store):
    with TestClient(_app(store)) as client:
        response = client.post("/api/records/notebooks/alice", json={"topic": "t", "content": "c", "tags": ["a"]})
    assert response.status_code == 200
    assert "tags:\n- a\n" in (store.repo_path / "notebooks" / "alice" / "t.md").read_text(encoding="utf-8")


class TestAFrontmatterTheStoreWritesIsOneTheStoreReads:
    @pytest.mark.parametrize(("slug", "kwargs"), [
        pytest.param("review-nominal", {"metrics": {"sample": (1, 2)}}, id="a-tuple-in-metrics-case-B"),
        pytest.param("review---nominal", {"metrics": {"sample": (1, 2)}}, id="a-tuple-in-metrics-and-three-hyphens-in-the-topic-case-A"),
        pytest.param("review-extra", {"extra_frontmatter": {"env": (1, 2)}}, id="a-tuple-in-an-envelope"),
        pytest.param("review-pairs", {"metrics": {"sample": [(1, 2), (3, 4)]}}, id="a-list-of-tuples"),
        pytest.param("review-deep", {"metrics": {"a": {"b": ({"c": (1,)},)}}}, id="tuples-nested-in-mappings"),
    ])
    async def test_a_tuple_is_written_as_a_list_and_the_note_stays_private(self, store, slug, kwargs):
        path = await store.write_notebook("alice", slug, "coolant private body", **kwargs)
        assert path in await _hits(store, "alice"), "premise: the author finds her own note"
        assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
        assert await store.read_entry(path, reader_id="bob") is None
        assert path not in await _hits(store, "bob")
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"]["classification"] == "private"
        await store.publish(path, "alice")
        assert await store.read_entry(path, reader_id="bob") is None

    @pytest.mark.parametrize("where", ["metrics", "extra_frontmatter"])
    @pytest.mark.parametrize("value", [
        pytest.param(_Plain(), id="an-object"),
        pytest.param(collections.OrderedDict(a=1), id="an-ordered-dict"),
        pytest.param(frozenset({1}), id="a-frozenset"),
        pytest.param(_Pair(1, 2), id="a-named-tuple"),
        pytest.param(_Text("x"), id="a-str-subclass"),
        pytest.param({(1, 2): "x"}, id="a-tuple-as-a-key"),
    ])
    async def test_a_value_no_reader_loads_is_refused_before_a_file_is_touched(self, store, where, value):
        first = await store.write_notebook("alice", "keep", "coolant first body", metrics={"m": [1]})
        before = (store.repo_path / first).read_bytes()
        kwargs = {"metrics": {"sample": value}} if where == "metrics" else {"extra_frontmatter": {"env": value}}
        key = "metrics" if where == "metrics" else "env"
        refused = []
        for callsign, slug in (("alice", "keep"), ("zed", "fresh")):
            try:
                await store.write_notebook(callsign, slug, "coolant other body", **kwargs)
            except ValueError as exc:
                refused.append(str(exc))
        assert len(refused) == 2, "an update and a create are both refused with ValueError"
        assert all(key in message for message in refused)
        assert (store.repo_path / first).read_bytes() == before
        assert [p.name for p in store.repo_path.rglob("*.md")] == ["keep.md"] and not (store.repo_path / "notebooks" / "zed").exists()

    async def test_a_publish_of_a_hand_made_note_holding_an_ordered_mapping_writes_no_python_tag(self, store):
        """``safe_load`` builds a list of tuples for ``!!omap``; ``publish`` re-dumps what it loaded."""
        path = "notebooks/alice/omap.md"
        _hand_made(store, path, "---\nauthor: alice\nclassification: private\nsteps: !!omap [a: 1, b: 2]\n---\n\ncoolant private body\n")
        assert path in await _hits(store, "alice"), "premise: the author finds her own note"
        await store.publish(path, "alice")
        assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
        assert await store.read_entry(path, reader_id="bob") is None

    def test_a_skill_rewrite_of_a_file_holding_an_ordered_mapping_stays_readable(self, tmp_path):
        path = tmp_path / "demo-skill" / "SKILL.md"
        path.parent.mkdir()
        path.write_text("---\nname: demo-skill\ndescription: Use when needed\nsteps: !!omap [a: 1, b: 2]\n---\n\n# Demo\n", encoding="utf-8")
        entry = parse_skill_file(path)
        assert entry is not None, "premise: it parses before the rewrite"
        entry.department = "operations"
        CognitiveSkillCatalog._rewrite_frontmatter(path, entry)
        assert "!!python" not in path.read_text(encoding="utf-8")
        assert parse_skill_file(path) is not None


class TestANumericTagReachesTheIndexAndANonListIsRefused:
    @pytest.mark.parametrize("tags", [
        pytest.param([717], id="an-integer"),
        pytest.param([717, "x"], id="an-integer-and-text"),
        pytest.param([1.5], id="a-float"),
        pytest.param([True], id="a-boolean"),
    ])
    async def test_a_tag_that_is_not_text_reaches_the_index_on_write_and_on_backfill(self, store, tags):
        layer = SemanticKnowledgeLayer(store.repo_path.parent / "semantic")
        column = _Collection()
        layer._collections = {"records": column}
        store.set_semantic_indexer(layer)
        path = await store.write_notebook("alice", "tagged", "coolant body", tags=tags, classification="ship")
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"]["tags"] == tags, "premise: the tags are kept as given"
        assert f"record_{path}" in column.rows, "the write indexed the record"
        assert str(tags[0]) in column.rows[f"record_{path}"][0].split("\n")[0]
        column.rows.clear()
        assert await layer.reindex_records(store) == 1 and f"record_{path}" in column.rows

    @pytest.mark.parametrize("tags", [
        pytest.param(717, id="an-integer"),
        pytest.param("abc", id="a-string"),
        pytest.param({"a": 1}, id="a-mapping"),
        pytest.param({"x"}, id="a-set"),
    ])
    async def test_a_tags_value_that_is_not_a_list_is_refused(self, store, tags):
        try:
            await store.write_notebook("alice", "scalar", "coolant body", tags=tags)
        except ValueError as exc:
            message = str(exc)
        else:
            message = None
        assert message is not None and "tags must be a list" in message
        assert list(store.repo_path.rglob("*.md")) == []

    async def test_a_tuple_of_tags_is_written_as_a_list(self, store):
        path = await store.write_notebook("alice", "tupled", "coolant body", tags=("a", "b"))
        assert "!!python" not in (store.repo_path / path).read_text(encoding="utf-8")
        own = await store.read_entry(path, reader_id="alice")
        assert own is not None and own["frontmatter"]["tags"] == ["a", "b"]

    def test_the_notebook_route_answers_400_for_a_tags_value_that_is_not_a_list(self, store):
        with TestClient(_app(store)) as client:
            response = client.post("/api/records/notebooks/alice", json={"topic": "t", "content": "c", "tags": 717})
        assert response.status_code == 400 and "tags must be a list" in response.json()["error"]
