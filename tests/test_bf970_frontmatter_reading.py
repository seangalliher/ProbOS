"""BF-970 (#1801): Ship's Records read a frontmatter block one way, with a fixed nesting limit, and fail closed.

Every reader reads a block through ``probos.utils.frontmatter.load_frontmatter``. A block YAML refuses, or one holding
``FRONTMATTER_DEPTH_LIMIT`` (64) collections open at once or more, is unparsed, and the access rules read the stand-in
(``_unparsed_gate``: private to the owner of its ``notebooks/<callsign>/`` directory). BF-940 A1 (reading the base's cut of the
text where the block did not load) is gone, and ``dump_frontmatter`` refuses what no reader would load. Real ``RecordsStore`` over
``tmp_path`` with ``~`` moved and hand-made documents; no network. Each case asserts its premise first; the new module names are
read as attributes, so on the base a case fails at its own line, not at import.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import FRONTMATTER_UNPARSED_KEY, RecordsStore
from probos.utils import frontmatter as frontmatter_module
from probos.utils.frontmatter import base_split_frontmatter, dump_frontmatter

_LIMIT = 64  # the issue's limit: a block holding 64 collections open at once is unparsed, and one holding 63 loads
_BODY = "warp private body"
_LIBYAML = bool(getattr(yaml, "__with_libyaml__", False))
_LOADERS = [yaml.SafeLoader, *([yaml.CSafeLoader] if _LIBYAML else [])]
#: The issue's first acceptance shape: a ``---`` inside a value, then ``classification: private``, then a tag ``safe_load``
#: refuses. The base's cut (``a: x``) loads and names no classification, so A1 read the note as ``ship``.
_A1_BLOCK = "a: x --- y\nclassification: private\nauthor: alice\nsample: !!python/tuple [1, 2]\n"
#: A block PyYAML refuses (a tab after a key) and libyaml reads, whose base cut (``a: x``) loads and names no classification.
_TAB_BLOCK = "a: x --- y\nnote:\tabc\n"


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


def _healthy(store: RecordsStore, path: str, body: str) -> None:
    values = {"author": "captain", "classification": "ship", "status": "published"}
    _hand_made(store, path, f"---\n{yaml.safe_dump(values, sort_keys=False)}---\n\n{body}\n")


async def _found(store: RecordsStore, reader_id: str | None, query: str = "warp") -> list[str]:
    return [hit["path"] for hit in await store.search(query, scope="ship", reader_id=reader_id)]


async def _scores(store: RecordsStore, reader_id: str) -> dict[str, float]:
    return {hit["path"]: hit["score"] for hit in await store.search("warp coolant", scope="ship", reader_id=reader_id)}


async def _attempt(call: Any) -> tuple[type | None, str]:
    try:
        await call
    except Exception as exc:  # noqa: BLE001 -- the case asserts on the type and the text
        return type(exc), str(exc)
    return None, ""


def _nest(depth: int, style: str = "flow") -> str:
    """A block holding ``depth`` collections open at once, its top-level mapping included, in flow or block style."""
    inner = depth - 1
    nest = "[" * inner + "x" + "]" * inner if style == "flow" else "\n" + "- " * inner + "x"
    return f"author: alice\nclassification: ship\nnest: {nest}\n"


def _open_at_once(text: str) -> int:
    """The most collections open at once in ``text``, counted from PyYAML's own event stream (each depth's premise)."""
    depth = deepest = 0
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            deepest = max(deepest, depth)
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    return deepest


def _mapping(depth: int) -> Any:
    """``depth`` nested single-key mappings around a leaf."""
    value: Any = "leaf"
    for _ in range(depth):
        value = {"k": value}
    return value


async def _padded(pad: int, call: Any) -> Any:
    """``await call()`` with ``pad`` more coroutine frames beneath it."""
    if pad:
        return await _padded(pad - 1, call)
    return await call()


def _deep(pad: int, call: Any) -> Any:
    """``call()`` with ``pad`` more frames beneath it."""
    if pad:
        return _deep(pad - 1, call)
    return call()


def _stack_depth() -> int:
    count, frame = 0, sys._getframe()
    while frame is not None:
        count, frame = count + 1, frame.f_back
    return count


def _with_frames_left(left: int, call: Any) -> Any:
    """``call()`` from a stack about ``left`` frames below the recursion limit."""
    if _stack_depth() < sys.getrecursionlimit() - left:
        return _with_frames_left(left, call)
    return call()


def _alias_block(shape: str) -> str:
    """AD-1341 S5's alias graphs (register F-661): a 5,000-link chain, or a 22-level doubling graph (a billion laughs)."""
    if shape == "chain":
        anchors = ["n0: &n0 [x]", *(f"n{i}: &n{i} [*n{i - 1}]" for i in range(1, 5000))]
        top = 4999
    else:
        anchors = ["n0: &n0 [x]", *(f"n{i}: &n{i} [*n{i - 1}, *n{i - 1}]" for i in range(1, 23))]
        top = 22
    return "author: alice\nclassification: ship\n" + "\n".join(anchors) + f"\ngraph: *n{top}\n"


async def test_a_document_only_its_cut_reads_is_unparsed_in_every_reader(store):
    """T1, acceptance 1. ``safe_load`` refuses the block (a ``!!python/tuple`` after ``classification: private``), and the base's
    cut, the block up to the ``---`` inside the first value, loads as ``{"a": "x"}``, which names no classification: A1 read it as
    ``ship`` and showed it to every reader. The block is unparsed now: ``read_entry``, the search and ``list_entries`` apply the
    stand-in (private to the owner of ``notebooks/alice/``), and ``publish`` refuses it. The last three lines are the seams each A1
    clause stood in (mutation rows R1 to R3)."""
    raw = _raw(_A1_BLOCK)
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_A1_BLOCK)
    cut, _ = base_split_frontmatter(raw)
    assert yaml.safe_load(cut) == {"a": "x"}, "premise: the base's cut loads and names no classification (it read as ship)"
    path = "notebooks/alice/a1.md"
    _hand_made(store, path, raw)
    _healthy(store, "reports/open.md", "warp open body")
    assert await store.read_entry(path, reader_id="bob") is None
    assert await store.read_entry(path, reader_id="alice") == {"frontmatter": {}, "content": _BODY, "path": path}
    assert (await store.read_entry(path, reader_id="captain"))["frontmatter"] == {}
    assert await _found(store, "bob") == ["reports/open.md"]
    assert path in await _found(store, "alice") and path in await _found(store, "captain")
    listed = {entry["path"]: entry for entry in await store.list_entries()}
    assert listed[path] == {"path": path, "frontmatter": {}, FRONTMATTER_UNPARSED_KEY: True}
    kind, message = await _attempt(store.publish(path, "alice"))
    assert kind is ValueError and path in message
    assert records_store_module._load_document(raw) == ({}, _BODY, True)
    frontmatter, _, block, unparsed = records_store_module._search_read_document(raw)
    assert (frontmatter, unparsed) == ({}, True)
    assert records_store_module._base_reading_admits(block, scope="ship", reader_id="bob", reader_department="", path=path) is False


async def test_a_document_only_its_cut_reads_moves_no_score_of_a_reader_it_is_withheld_from(store, tmp_path):
    """T2, acceptance 1, the search's first pass (mutation row R2): A1's first pass read the cut, admitted bob, and so counted the
    note toward the rarity of the terms bob searches (BF-952 A4). Unparsed, it counts only for the readers the stand-in admits."""
    plain = _make_store(tmp_path / "plain")
    for target in (store, plain):
        _healthy(target, "reports/h1.md", "warp")
        _healthy(target, "reports/h2.md", "coolant")
    _hand_made(store, "notebooks/alice/a1.md", _raw(_A1_BLOCK, "warp"))
    expected = await _scores(plain, "bob")
    assert set(expected) == {"reports/h1.md", "reports/h2.md"}, "premise: the healthy records are found"
    assert await _scores(store, "captain") != await _scores(plain, "captain"), "premise: a note a reader may read moves her scores"
    assert await _scores(store, "bob") == expected


async def test_a_block_only_libyaml_reads_whose_cut_loads_is_withheld_from_another_reader(store, monkeypatch):
    """T3, acceptance 1, the search's second reading (mutation row R3). PyYAML refuses the block (a tab after a key) and libyaml
    reads it as a mapping that names no classification, so under libyaml the first pass admits bob; A1's second reading read the
    cut (``a: x``: no classification, ``ship``) and admitted him too. The second reading now applies the stand-in. Under PyYAML's
    loader the first pass reads the block as unparsed, so only a host with libyaml kills R3 here (T1 kills it on any host)."""
    path = "notebooks/alice/tab.md"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_TAB_BLOCK)
    if _LIBYAML:
        assert yaml.load(_TAB_BLOCK, Loader=yaml.CSafeLoader) == {"a": "x --- y", "note": "abc"}, "premise: libyaml reads it"
    _hand_made(store, path, _raw(_TAB_BLOCK))
    _healthy(store, "reports/open.md", "warp open body")
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        assert await _found(store, "bob") == ["reports/open.md"], loader
        assert path in await _found(store, "alice") and path in await _found(store, "captain"), loader


@pytest.mark.parametrize("style", ["flow", "block"])
async def test_a_block_holding_64_collections_open_is_unparsed_in_every_reader_from_50_frames_and_63_loads(
    store, monkeypatch, caplog, style,
):
    """T4, acceptance 2. The nesting is checked with a parse that does not recurse, so the answer does not depend on the frames
    above the reader: each reader is called from 50 extra frames. The base loaded both blocks from here (PyYAML raises only past
    about 330 levels), so a 64-level note named ``ship`` was shown to bob (mutation rows R4 to R6)."""
    shallow, deep = _nest(_LIMIT - 1, style), _nest(_LIMIT, style)
    assert (_open_at_once(shallow), _open_at_once(deep)) == (_LIMIT - 1, _LIMIT), "premise: the depths, from PyYAML's events"
    assert yaml.safe_load(deep)["classification"] == "ship", "premise: the base's call loads 64 levels from here"
    loaded, refused = "notebooks/alice/shallow.md", "notebooks/alice/deep.md"
    _hand_made(store, loaded, _raw(shallow))
    _hand_made(store, refused, _raw(deep))
    assert await _padded(50, lambda: store.read_entry(refused, reader_id="bob")) is None
    assert (await _padded(50, lambda: store.read_entry(refused, reader_id="captain")))["frontmatter"] == {}
    near = await _padded(50, lambda: store.read_entry(loaded, reader_id="bob"))
    assert near is not None and near["frontmatter"]["classification"] == "ship"
    listed = {entry["path"]: entry for entry in await _padded(50, store.list_entries)}
    assert listed[refused] == {"path": refused, "frontmatter": {}, FRONTMATTER_UNPARSED_KEY: True}
    assert FRONTMATTER_UNPARSED_KEY not in listed[loaded] and listed[loaded]["frontmatter"]["classification"] == "ship"
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        seen = await _padded(50, lambda: _found(store, "bob"))
        assert loaded in seen and refused not in seen, loader
        assert refused in await _padded(50, lambda: _found(store, "captain")), loader
        assert _deep(50, lambda chosen=loader: frontmatter_module.load_frontmatter(deep, chosen)) == ({}, True), loader
        assert _deep(50, lambda chosen=loader: frontmatter_module.load_frontmatter(shallow, chosen))[1] is False, loader
    admits = records_store_module._base_reading_admits
    assert _deep(50, lambda: admits(deep, scope="ship", reader_id="bob", reader_department="", path=refused)) is False
    assert _deep(50, lambda: admits(shallow, scope="ship", reader_id="bob", reader_department="", path=loaded)) is True
    kind, message = await _attempt(_padded(50, lambda: store.publish(refused, "captain")))
    assert kind is ValueError and refused in message
    with caplog.at_level(logging.WARNING, logger="probos.knowledge.records_store"):
        await _padded(50, lambda: store.write_entry("alice", refused, "replacement body", "probe", classification="private"))
    assert any(refused in record.getMessage() for record in caplog.records if record.levelno == logging.WARNING)


async def test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records(store, monkeypatch):
    """T5, acceptance 3. A block nesting 400 collections deep, and one as deep as the recursion limit (past what PyYAML loads), are
    unparsed: the search returns the other records to every reader and finds those two for the Captain and their owner only, and
    ``read_entry`` and ``list_entries`` read them as ``{}``. The base either loaded the 400-level note (named ``ship``, shown to bob)
    or raised ``RecursionError`` for it and withheld it from the Captain too; it withheld the deeper one from everyone."""
    limit = sys.getrecursionlimit()
    deep, deeper = _nest(400), _nest(limit)
    assert (_open_at_once(deep), _open_at_once(deeper)) == (400, limit), "premise: the depths, from PyYAML's events"
    with pytest.raises(RecursionError):
        yaml.safe_load(deeper)  # premise: past what PyYAML's composer loads
    others = ["reports/a.md", "reports/b.md"]
    for path in others:
        _healthy(store, path, "warp report")
    nested = ["notebooks/alice/deep.md", "notebooks/alice/deeper.md"]
    _hand_made(store, nested[0], _raw(deep))
    _hand_made(store, nested[1], _raw(deeper))
    for loader in _LOADERS:
        monkeypatch.setattr(records_store_module, "_RECORDS_YAML_LOADER", loader)
        assert sorted(await _found(store, "bob")) == others, loader
        assert sorted(await _found(store, "captain")) == sorted(others + nested), loader
        assert sorted(await _found(store, "alice")) == sorted(others + nested), loader
    for path in nested:
        assert (await store.read_entry(path, reader_id="captain"))["frontmatter"] == {}, path
    listed = {entry["path"]: entry for entry in await store.list_entries()}
    assert all(listed[path].get(FRONTMATTER_UNPARSED_KEY) is True for path in nested)


@pytest.mark.parametrize("loader", _LOADERS, ids=lambda loader: loader.__name__)
def test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit(loader):
    """T6. The check reads the parser's event stream and builds no node, so it needs a few frames whatever the depth: from a stack
    40 frames below the recursion limit, where PyYAML cannot load a 63-level block, it answers for 63, 64 and ten times the limit.
    Siblings add no depth; a parse error is the load's to read (YAML's refusal); a block that loads to nothing is not unparsed."""
    assert frontmatter_module.FRONTMATTER_DEPTH_LIMIT == _LIMIT
    check = frontmatter_module.frontmatter_nests_too_deep
    huge = _nest(10 * sys.getrecursionlimit())
    with pytest.raises(RecursionError):
        _with_frames_left(40, lambda: yaml.load(_nest(_LIMIT - 1), Loader=yaml.SafeLoader))  # premise: no room for a 63-level load
    answers = _with_frames_left(40, lambda: (check(_nest(_LIMIT - 1), loader), check(_nest(_LIMIT), loader), check(huge, loader)))
    assert answers == (False, True, True)
    assert check("tags: [" + ", ".join(["[warp]"] * 150) + "]", loader) is False  # 3 deep, 152 collections
    assert check("broken: [unclosed", loader) is False
    assert frontmatter_module.load_frontmatter("broken: [unclosed", loader) == ({}, True)
    assert frontmatter_module.load_frontmatter("[]", loader) == ({}, False)


def test_dump_frontmatter_refuses_a_mapping_holding_64_collections_open_and_writes_63():
    """T7. ``dump_frontmatter`` refuses (``ValueError``) what no reader loads, naming the key and the limit, never a value; 63 levels
    are written and read back (mutation rows R8, R9). A mapping that holds itself is written with an alias, which opens no
    collection, and still reads back: the check measures the text the readers read, not the Python object."""
    fits = {"k_good": 1, "k_fine": _mapping(_LIMIT - 2)}
    too_deep = {"k_good": 1, "k_bad": _mapping(_LIMIT - 1)}
    assert (_open_at_once(yaml.safe_dump(fits)), _open_at_once(yaml.safe_dump(too_deep))) == (_LIMIT - 1, _LIMIT), "premise: the depths"
    assert yaml.safe_load(dump_frontmatter(fits)) == fits
    with pytest.raises(ValueError) as info:
        dump_frontmatter(too_deep)
    message = str(info.value)
    assert "k_bad" in message and "k_good" not in message and str(_LIMIT) in message and "leaf" not in message
    looped: dict[str, Any] = {"author": "alice"}
    looped["self"] = looped
    text = dump_frontmatter(looped)
    assert _open_at_once(text) == 1 and "*" in text


async def test_write_entry_refuses_a_64_level_value_before_touching_the_file_and_round_trips_63(store):
    """T8. The store never writes what it would refuse to read: ``write_entry`` raises before any file is touched (the notebook
    route answers that ``ValueError`` with HTTP 400), and the deepest value it writes reads back whole."""
    path = "notebooks/alice/deep.md"
    with pytest.raises(ValueError) as info:
        await store.write_entry("alice", path, "warp body", "probe", classification="private", metrics=_mapping(_LIMIT - 1))
    assert "metrics" in str(info.value) and not (store.repo_path / path).exists()
    await store.write_entry("alice", path, "warp body", "probe", classification="private", metrics=_mapping(_LIMIT - 2))
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"]["metrics"] == _mapping(_LIMIT - 2)
    assert await store.read_entry(path, reader_id="bob") is None


@pytest.mark.parametrize("shape", ["chain", "doubling"])
async def test_an_alias_graph_opens_no_collection_and_reads_as_before_in_bounded_time(store, shape):
    """T9, guard (passes on the base). An alias adds no depth to the check, which follows none, and the load builds each anchored
    node once, so a 5,000-link chain and a doubling graph read as before, quickly: the note is ``ship``, shown to bob and found."""
    block = _alias_block(shape)
    assert _open_at_once(block) == 2, "premise: every collection is a sequence under the mapping"
    path = "notebooks/alice/alias.md"
    _hand_made(store, path, _raw(block))
    started = time.perf_counter()
    entry = await store.read_entry(path, reader_id="bob")
    found = await _found(store, "bob")
    assert time.perf_counter() - started < 30.0  # a hang guard, as AD-1341 S5's
    assert entry is not None and entry["frontmatter"]["classification"] == "ship"
    assert found == [path]
