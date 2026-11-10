"""BF-940 (#1686): a document's frontmatter ends at a line of its own, so a value holding ``---`` is not cut short.

The real RecordsStore over ``tmp_path`` (its git repository too; no network) with HOME moved there, and the real skill catalog's
functions over SKILL.md files in ``tmp_path``. The functions before the class pass on both trees; the class holds the cases the
unfixed tree fails. No BF-940 name is imported.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.cognitive.skill_catalog import CognitiveSkillCatalog, get_skill_body, parse_skill_file
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore

_BODY = "PRIVATE_BODY_PROOF the coolant"
_VALUES = ("---", "----", "--- x", "x ---", "---x", "x --- y", "a\n---\nb", "a\r\n---\r\nb", "- - -", "---\n---", "x: ---", "'---'")


async def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordsStore:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _bare(tmp_path: Path) -> RecordsStore:
    return RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))


def _hyphens(line: str) -> int:
    """The hyphens of a line of only hyphens (three or more) and trailing blanks, else 0: the test's own rule."""
    bare = line.rstrip(" \t\r")
    return len(bare) if len(bare) >= 3 and set(bare) == {"-"} else 0


def _closing(raw: str) -> tuple[int, int] | None:
    """(offset, hyphens) of the first line after the first that is only hyphens, for a text that begins with ``---``."""
    if not raw.startswith("---") or "\n" not in raw:
        return None
    offset = raw.index("\n") + 1
    for line in raw[offset:].split("\n"):
        if _hyphens(line):
            return offset, _hyphens(line)
        offset += len(line) + 1
    return None


def reframed(raw: str) -> bool:
    """Whether the rule frames ``raw`` otherwise than the base: a ``---`` inside a line before the first closing line, or a
    closing line of more than three hyphens (the base left the rest of them at the start of the body)."""
    found = _closing(raw)
    return found is not None and ("---" in raw[3:found[0]] or found[1] > 3)


def _oracle(raw: str) -> tuple[Any, str]:
    """The rule as a loop over the lines, not a pattern: what every reader's reading is compared with."""
    block = rest = None
    if raw.startswith("---"):
        found = _closing(raw)
        if found is not None:
            block, rest = raw[3:found[0]], raw[found[0] + found[1]:]
        elif len(parts := raw.split("---", 2)) >= 3:  # no closing line: the base's reading (L18)
            block, rest = parts[1], parts[2]
    if block is None:
        return {}, raw
    try:
        return yaml.safe_load(block) or {}, rest.strip()
    except yaml.YAMLError:
        return {}, rest.strip()


def _read_or_error(read: Any, raw: str) -> Any:
    try:
        return read(raw)
    except Exception as exc:  # noqa: BLE001 -- compared, never swallowed: a constructor error must be the same error
        return type(exc).__name__


def _search_read(raw: str) -> tuple[Any, str]:
    return records_store_module._search_read_document(raw)[:2]


def grid() -> list[str]:
    """BF-952's T22 corpus, 3,747 documents: (12 + 144) line sequences x 3 closing lines x 4 bodies x 2 line endings, + 3."""
    lines = (
        "author: alice", "author: alice --- legacy", "author: Ezri---Prime", "classification: private", "classification: ship",
        "classification: private --- legacy", "department: medical", "topic: Review --- nominal", "topic: 2026-13-05---nominal",
        "topic: 'Inspection --- status: nominal'", "broken: [unclosed", "updated: 2026-13-05",
    )
    shapes = [
        "---\n" + "".join(f"{line}\n" for line in seq) + close + body
        for count in (1, 2) for seq in itertools.product(lines, repeat=count)
        for close in ("---\n", "----\n", "") for body in ("", "warp notes\n", "classification: ship\nauthor: bob\n", "---\nmore notes\n")
    ]
    shapes += [shape.replace("\n", "\r\n") for shape in shapes]
    return shapes + ["no frontmatter", "-- two hyphens\n---\nbody", "\n---\nauthor: alice\n---\nbody"]


async def _round_trip(store: RecordsStore, author: str, values: dict[str, Any], body: str = _BODY) -> None:
    """One private record through write_entry, read_entry, list_entries, search, update-in-place and publish."""
    path = "notebooks/Ezri/inspection.md"
    call = {"author": author, "path": path, "content": body, "message": "probe", "classification": "private", **values}
    await store.write_entry(**call)
    raw = (store.repo_path / path).read_text(encoding="utf-8")
    assert raw.endswith(body) and sum(1 for line in raw[: len(raw) - len(body)].split("\n") if _hyphens(line)) == 2, "premise: two delimiters"
    expected = {k: v for k, v in values.items() if k != "extra_frontmatter"} | values.get("extra_frontmatter", {})
    try:
        own = await store.read_entry(path, reader_id=author)
    except Exception as exc:  # the base raises for a bad timestamp before its cut: a failure of the case
        raise AssertionError(f"read_entry raised {type(exc).__name__}") from exc
    assert own is not None and own["frontmatter"].get("classification") == "private" and own["frontmatter"].get("author") == author
    assert {key: own["frontmatter"].get(key) for key in expected} == expected and own["content"] == body
    assert await store.read_entry(path, reader_id="alice") is None
    assert [e["frontmatter"].get("classification") for e in await store.list_entries("notebooks") if e["path"] == path] == ["private"]
    assert await store.search("coolant", reader_id="alice") == []
    hits = await store.search("coolant", reader_id=author)
    assert [hit["path"] for hit in hits] == [path] and hits[0]["snippet"] == body[:200]
    await store.write_entry(**call)  # update-in-place carries ``created`` forward and counts the revision
    again = await store.read_entry(path, reader_id=author)
    assert again is not None and again["frontmatter"].get("revision") == 2 and again["frontmatter"].get("created") == own["frontmatter"].get("created")
    await store.publish(path, author)
    done = await store.read_entry(path, reader_id=author)
    assert done is not None and done["frontmatter"].get("status") == "published" and done["content"] == body
    assert done["frontmatter"].get("classification") == "private" and {key: done["frontmatter"].get(key) for key in expected} == expected


@pytest.mark.parametrize(("values", "body"), [
    pytest.param({"topic": "Inspection nominal", "tags": ["warp core"]}, _BODY, id="no-three-hyphens-in-the-values"),
    pytest.param({}, "above the coolant\n\n---\n\nbelow", id="a-body-holding-a-rule"),
])
async def test_a_record_the_rule_does_not_reframe_goes_through_the_same_round_trip(tmp_path, monkeypatch, values, body):
    """The control of the class below, and a body holding a rule: the chain passes on both trees."""
    await _round_trip(await _store(tmp_path, monkeypatch), "Ezri", values, body)


async def test_the_writer_puts_no_line_of_only_hyphens_inside_the_frontmatter(tmp_path, monkeypatch):
    """The premise of the class: for each of ``_VALUES`` as author, topic and tag, the file holds its two delimiter lines only."""
    store = await _store(tmp_path, monkeypatch)
    for index, value in enumerate(_VALUES):
        for position, call in enumerate(({"author": value}, {"topic": value}, {"tags": [value]})):
            path = f"notebooks/Ezri/p{index}-{position}.md"
            await store.write_entry(**{"author": "Ezri", "path": path, "content": "body", "message": "probe", **call})
            assert sum(1 for line in (store.repo_path / path).read_text(encoding="utf-8").split("\n") if _hyphens(line)) == 2, (value, position)


@pytest.mark.parametrize(("raw", "frontmatter", "body"), [
    pytest.param("---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n", {"author": "bones", "classification": "ship"}, "Warp report.", id="the-store-shape"),
    pytest.param("---\r\nauthor: bones\r\n---\r\n\r\nbody\r\n", {"author": "bones"}, "body", id="crlf-endings"),
    pytest.param("---\nauthor: bones\n---   \n\nbody", {"author": "bones"}, "body", id="a-closing-line-with-trailing-blanks"),
    pytest.param("---\nauthor: bones\n---", {"author": "bones"}, "", id="the-closing-line-ends-the-file"),
    pytest.param("---\nauthor: bones\n---\nabove\n\n---\n\nbelow", {"author": "bones"}, "above\n\n---\n\nbelow", id="a-body-holding-rules"),
    pytest.param("\ufeff---\nauthor: bones\n---\nbody", {}, "\ufeff---\nauthor: bones\n---\nbody", id="a-byte-order-mark-opens-no-frontmatter"),
    pytest.param("---\nauthor: alice\nwarp notes\n", {}, "---\nauthor: alice\nwarp notes\n", id="an-opener-and-no-later-hyphens-L18"),
    pytest.param(
        "---\nauthor: alice\nclassification: private --- inline\nbody", {"author": "alice", "classification": "private"}, "inline\nbody",
        id="hyphens-inside-a-line-and-no-closing-line-read-as-before",
    ),
    pytest.param("---\nkey: [unclosed\n---\nbody", {}, "body", id="frontmatter-that-does-not-parse-reads-as-empty-L19"),
])
def test_a_document_the_rule_does_not_reframe_reads_as_before(tmp_path, raw, frontmatter, body):
    """Guards: ``_parse_document`` and the search's reader read each shape as the base did."""
    assert not reframed(raw), "premise: the rule frames this shape as the base did"
    assert _bare(tmp_path)._parse_document(raw) == (frontmatter, body) and _search_read(raw) == (frontmatter, body)


_SKILL = "---\nname: demo-skill\ndescription: Use when a task needs it --- or a peer asks\nlicense: MIT\n---\n\n# Demo\n\nSteps.\n\n---\n\nFooter.\n"
_SKILL_BODY = "# Demo\n\nSteps.\n\n---\n\nFooter."


def _skill(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "demo-skill" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def _rewritten(path: Path) -> Any:
    entry = parse_skill_file(path)
    entry.department = "operations"
    CognitiveSkillCatalog._rewrite_frontmatter(path, entry)
    return parse_skill_file(path)


def test_a_skill_file_without_three_hyphens_in_its_frontmatter_reads_and_rewrites_as_before(tmp_path):
    """Guard: its body holds rules, as a store document's may."""
    path = _skill(tmp_path, _SKILL.replace(" --- or", ", or"))
    entry = parse_skill_file(path)
    assert entry is not None and entry.description == "Use when a task needs it, or a peer asks" and get_skill_body(path) == _SKILL_BODY
    assert _rewritten(path).department == "operations" and get_skill_body(path) == _SKILL_BODY


class TestAValueHoldingThreeHyphensIsNotCutShort:
    @pytest.mark.parametrize(("author", "values"), [
        pytest.param("Ezri---Prime", {}, id="an-author-holding-three-hyphens"),
        pytest.param("Ezri---", {}, id="an-author-ending-in-three-hyphens"),
        pytest.param("Ezri", {"topic": "Inspection --- status: nominal"}, id="a-quoted-topic-holding-a-key"),
        pytest.param("Ezri", {"topic": "first line\n---\nlast line"}, id="a-multi-line-topic-holding-a-rule"),
        pytest.param("Ezri", {"tags": ["warp --- core"]}, id="a-tag-holding-three-hyphens"),
        pytest.param("Ezri", {"extra_frontmatter": {"zz_note": "end --- of the envelope"}}, id="the-last-key-holding-three-hyphens"),
        pytest.param("Ezri", {"extra_frontmatter": {"due": "2026-13-05---nominal"}}, id="a-value-whose-cut-prefix-is-a-bad-timestamp"),
    ])
    async def test_a_record_holding_it_is_read_whole_listed_found_updated_and_published(self, tmp_path, monkeypatch, author, values):
        """BF-952's T16 (its four cases first), and the premise of its T17: the quoted topic parses. The last case's cut prefix,
        ``2026-13-05``, is a constructor error on the base: ``read_entry`` raised."""
        await _round_trip(await _store(tmp_path, monkeypatch), author, values)

    @pytest.mark.parametrize(("raw", "body"), [
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n---\n\nbody", "body", id="lf"),
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n----\n\nbody", "body", id="four-hyphens"),
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n---  \n\nbody", "body", id="trailing-blanks"),
        pytest.param("---\r\nauthor: Normal---Name\r\nclassification: private\r\n---\r\n\r\nbody", "body", id="crlf"),
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n---", "", id="the-end-of-the-file"),
    ])
    def test_each_closing_line_ends_the_frontmatter_after_a_value_holding_three_hyphens(self, tmp_path, raw, body):
        want = ({"author": "Normal---Name", "classification": "private"}, body)
        assert _bare(tmp_path)._parse_document(raw) == want and _search_read(raw) == want

    def test_a_four_hyphen_closing_line_leaves_nothing_of_itself_in_the_body(self, tmp_path):
        assert _bare(tmp_path)._parse_document("---\nauthor: bones\n----\n\nbody") == ({"author": "bones"}, "body")

    @pytest.mark.parametrize(("raw", "frontmatter", "body", "readers"), [
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nstatus: nominal\n---\nwarp notes\n",
            {"author": "alice", "classification": "private --- inline", "status": "nominal"}, "warp notes", {"alice", "bob"},
            id="then-a-key-and-a-rule",
        ),
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nWarp notes, in prose.\n---\nmore warp notes\n",
            {}, "more warp notes", {"alice", "bob"}, id="then-prose-and-a-rule",
        ),
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nclassification: ship\n---\nwarp notes\n",
            {"author": "alice", "classification": "ship"}, "warp notes", {"alice", "bob"}, id="then-a-repeated-key-and-a-rule",
        ),
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nclassification: private\nauthor: bob\n---\nwarp notes\n",
            {"author": "bob", "classification": "private"}, "warp notes", {"bob"}, id="then-keys-naming-another-author-and-a-rule",
        ),
    ])
    async def test_a_hand_made_document_closed_inside_a_line_reads_to_its_closing_line(
        self, tmp_path, monkeypatch, raw, frontmatter, body, readers,
    ):
        """The four BF-952 T20 / round-3 shapes that have a closing line after the inline marker. The base read each as alice's
        private note; the inline marker now ends nothing, so each reads to its closing line, as here, and ``read_entry`` admits
        the readers listed. No writer in the repository makes such a document (L3)."""
        store = await _store(tmp_path, monkeypatch)
        (store.repo_path / "notebooks" / "alice").mkdir(parents=True)
        (store.repo_path / "notebooks" / "alice" / "framing.md").write_text(raw, encoding="utf-8")
        assert store._parse_document(raw) == (frontmatter, body)
        assert {who for who in ("alice", "bob") if await store.read_entry("notebooks/alice/framing.md", reader_id=who)} == readers

    def test_every_document_of_the_grid_reads_by_the_rule(self, tmp_path):
        """BF-952's T22 over its 3,747 shapes, rewritten: both readers read each as ``_oracle`` does, a constructor error
        included. Premise: ``reframed`` names 2,388 of them, and the base differs from the rule on those and no others."""
        store, shapes = _bare(tmp_path), grid()
        assert len(shapes) == 3747 and sum(map(reframed, shapes)) == 2388, "premise: the grid and its reframed shapes"
        differ = [s for s in shapes if _read_or_error(store._parse_document, s) != _read_or_error(_oracle, s) or _read_or_error(_search_read, s) != _read_or_error(_oracle, s)]
        assert differ == [], (len(differ), differ[:3])

    def test_a_skill_file_whose_frontmatter_holds_three_hyphens_is_read_whole_and_rewritten_whole(self, tmp_path):
        path = _skill(tmp_path, _SKILL)
        entry = parse_skill_file(path)
        assert entry is not None and entry.description == "Use when a task needs it --- or a peer asks" and entry.license == "MIT"
        assert get_skill_body(path) == _SKILL_BODY
        again = _rewritten(path)
        assert again is not None and again.description == entry.description and again.department == "operations"
        assert path.read_text(encoding="utf-8").endswith("---\n\n# Demo\n\nSteps.\n\n---\n\nFooter.\n")

    def test_a_skill_file_whose_quoted_description_holds_three_hyphens_and_a_colon_parses(self, tmp_path):
        path = _skill(tmp_path, '---\nname: demo-skill\ndescription: "Use --- when: needed"\n---\n\nBody.\n')
        entry = parse_skill_file(path)
        assert entry is not None and entry.description == "Use --- when: needed" and get_skill_body(path) == "Body."
