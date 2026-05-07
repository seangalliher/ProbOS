"""AD-562: Tests for backlinks helpers (extract / build_index / suggest)."""
from __future__ import annotations

import time

from probos.knowledge.backlinks import (
    BacklinkIndex,
    BacklinkRecord,
    Reference,
    build_backlink_index,
    extract_references,
    suggest_cross_references,
)


def test_reference_dataclass_is_frozen_and_round_trips() -> None:
    r = Reference(kind="callsign", target="chapel", raw_match="@chapel")
    assert r.kind == "callsign"
    assert r.target == "chapel"
    # Frozen dataclass prevents mutation
    try:
        r.kind = "tag"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("Reference should be frozen")


def test_backlink_record_and_index_construct() -> None:
    rec = BacklinkRecord(path="x.md", references=(), referenced_by=())
    idx = BacklinkIndex(records={"x.md": rec}, path_by_callsign={}, path_by_topic_slug={}, built_at=0.0, entry_count=1)
    assert idx.records["x.md"] is rec
    assert idx.entry_count == 1


def test_extract_references_empty_content_returns_empty() -> None:
    out = extract_references("", {}, valid_callsigns=set(), valid_topic_slugs=set())
    assert out == ()


def test_extract_references_wikilink_match() -> None:
    out = extract_references(
        "see [[chapel-trust-notes]] for details",
        {},
        valid_callsigns=set(), valid_topic_slugs=set(),
    )
    kinds = {r.kind for r in out}
    targets = {r.target for r in out}
    assert "wikilink" in kinds
    assert "chapel-trust-notes" in targets


def test_extract_references_callsign_match_and_email_skip() -> None:
    out = extract_references(
        "ping @chapel about foo@example.com",
        {},
        valid_callsigns={"chapel"}, valid_topic_slugs=set(),
    )
    cs = [r for r in out if r.kind == "callsign"]
    assert len(cs) == 1
    assert cs[0].target == "chapel"


def test_extract_references_unknown_callsign_filtered_out() -> None:
    out = extract_references(
        "@xyz @chapel",
        {},
        valid_callsigns={"chapel"}, valid_topic_slugs=set(),
    )
    targets = {r.target for r in out if r.kind == "callsign"}
    assert targets == {"chapel"}


def test_extract_references_frontmatter_topic_slug_and_tags() -> None:
    out = extract_references(
        "",
        {"topic_slug": "Trust-System", "tags": ["routing", "trust"]},
        valid_callsigns=set(), valid_topic_slugs={"trust-system"},
    )
    assert any(r.kind == "topic_slug" and r.target == "trust-system" for r in out)
    tags = sorted(r.target for r in out if r.kind == "tag")
    assert tags == ["routing", "trust"]


def test_extract_references_dedupes_by_kind_target() -> None:
    out = extract_references(
        "[[foo]] [[foo]] [[foo]]",
        {},
        valid_callsigns=set(), valid_topic_slugs=set(),
    )
    assert len([r for r in out if r.kind == "wikilink" and r.target == "foo"]) == 1


def test_build_backlink_index_empty_entries() -> None:
    idx = build_backlink_index([], valid_callsigns=set())
    assert idx.records == {}
    assert idx.entry_count == 0
    assert idx.built_at <= time.time()


def test_build_backlink_index_bidirectional_callsign_link() -> None:
    entries = [
        {"path": "notebooks/chapel/n1.md", "frontmatter": {"author": "chapel"}, "content": "ping @data"},
        {"path": "notebooks/data/n2.md", "frontmatter": {"author": "data"}, "content": "hello"},
    ]
    idx = build_backlink_index(entries, valid_callsigns={"chapel", "data"})
    assert idx.path_by_callsign["chapel"] == "notebooks/chapel/n1.md"
    # data is referenced by chapel's note via @data callsign
    data_rec = idx.records["notebooks/data/n2.md"]
    assert "notebooks/chapel/n1.md" in data_rec.referenced_by


def test_build_backlink_index_topic_slug_resolution() -> None:
    entries = [
        {"path": "captains-log/c1.md", "frontmatter": {"topic_slug": "trust"}, "content": "see [[trust]]"},
        {"path": "manuals/m1.md", "frontmatter": {"topic_slug": "Trust"}, "content": ""},
    ]
    idx = build_backlink_index(entries, valid_callsigns=set())
    # First-seen wins for topic slug
    assert idx.path_by_topic_slug["trust"] == "captains-log/c1.md"


def test_suggest_cross_references_jaccard_threshold_gating() -> None:
    entries = [
        {"path": "a.md", "frontmatter": {"tags": ["trust", "routing", "consensus"], "author": "x"}},
        {"path": "b.md", "frontmatter": {"tags": ["trust", "routing"], "author": "x"}},
        {"path": "c.md", "frontmatter": {"tags": ["unrelated"], "author": "y"}},
    ]
    idx = build_backlink_index(entries, valid_callsigns=set())
    sugg = suggest_cross_references(entries, idx, jaccard_threshold=0.3, max_per_entry=5)
    # a and b share many tags + author → above threshold
    assert "a.md" in sugg
    assert any(s["path"] == "b.md" for s in sugg["a.md"])
    # c has nothing in common with a/b above threshold
    if "a.md" in sugg:
        assert all(s["path"] != "c.md" for s in sugg["a.md"])


def test_suggest_cross_references_zero_threshold_returns_empty() -> None:
    entries = [{"path": "a.md", "frontmatter": {"tags": ["x"]}}]
    idx = build_backlink_index(entries, valid_callsigns=set())
    sugg = suggest_cross_references(entries, idx, jaccard_threshold=0.0, max_per_entry=5)
    assert sugg == {}
