"""AD-1294 (#1090): a retrieved record must carry its author, and a retrieval
score must not be called confidence.

#1090's framing is PARTLY REFUTED by execution. It concluded:

    The agent had correct, complete, and *distinctly labelled* data for both.
    The summary misrepresented it. So the fix does not belong in retrieval.

Right about retrieval, wrong about rendering. Two defects sat between the two:

  1. ``crew_executor._render_commons_entry`` emitted ``OracleResult.score`` --
     a retrieval RELEVANCE -- to the agent under the word ``confidence``, with
     the docstring asserting the same mistake. The agent was faithfully
     repeating the system's own error, and an agent cannot be held to a
     distinction the prompt does not make.
  2. ``frontmatter.author`` was attached correctly by
     ``_query_records_semantic`` and rendered by NEITHER path. On the Oracle
     path the agent had the author only implicitly, encoded in a path string;
     on the crew path it had nothing at all, so any byline it offered was
     invention.

The fixes give the agent MORE true information, not less confidence (#13(b):
reach the capability by supplying the governed data). No reply text is
inspected anywhere here -- an attribution checker would be text-matching LLM
prose, which is the verdict shape AD-1285 built and deliberately deleted.

Every "renders nothing" test below first asserts the positive case renders
something with the same fixture shape: a formatter test that asserts an absent
substring passes trivially if the formatter was never called.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from probos.cognitive.crew_executor import (
    _COMMONS_DISPOSITION,
    _MAX_ENTRY_CHARS,
    _render_commons_entry,
)
from probos.cognitive.oracle_service import (
    OracleResult,
    OracleService,
    _decode_record_frontmatter,
)


def _result(
    *,
    content: str = "Coolant resonance peaks at 4.2 kHz.",
    score: float = 0.9,
    metadata: Any = None,
    provenance: str = "[ship's records]",
) -> OracleResult:
    return OracleResult(
        source_tier="records",
        content=content,
        score=score,
        metadata={} if metadata is None else metadata,
        provenance=provenance,
    )


class _FakeSemanticLayer:
    """Returns raw rows shaped exactly as ``_query_records_semantic`` expects.

    ``frontmatter_json`` is the serialised sidecar the real indexer writes, so
    the author travels the same decode path production uses -- not a
    hand-placed dict that would bypass ``_decode_record_frontmatter``.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[dict[str, Any]] = []

    async def search(self, query_text: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"query_text": query_text, **kwargs})
        return self._rows


def _row(*, author: str, path: str, snippet: str, score: float = 0.9) -> dict[str, Any]:
    return {
        "score": score,
        "document": snippet,
        "metadata": {
            "snippet": snippet,
            "path": path,
            "frontmatter_json": json.dumps({"author": author, "title": "note"}),
        },
    }


def _oracle_with(rows: list[dict[str, Any]]) -> OracleService:
    """An OracleService with only the semantic layer wired.

    ``__new__`` bypasses a constructor that needs the whole runtime; the two
    attributes below are the only ones the paths under test read.
    """
    svc = OracleService.__new__(OracleService)
    svc._semantic_layer = _FakeSemanticLayer(rows)
    svc._match_reason_enabled = False
    return svc


# =========================================================================== #
# 1-2. label correctness (Section 1)                                          #
# =========================================================================== #


def test_crew_marker_says_relevance_and_never_confidence() -> None:
    out = _render_commons_entry(_result(score=0.9))
    assert "relevance 0.90" in out
    assert "confidence" not in out


def test_a_frontmatter_confidence_is_not_conflated_with_the_relevance_score() -> None:
    """The two are different quantities and must not substitute for each other
    in either direction. The rendered number is the retrieval score; a
    frontmatter ``confidence`` is not promoted into the marker."""
    out = _render_commons_entry(
        _result(score=0.42, metadata={"frontmatter": {"confidence": 0.99}})
    )
    assert "relevance 0.42" in out
    assert "0.99" not in out
    assert "confidence" not in out


def test_disposition_text_teaches_relevance_and_never_confidence() -> None:
    """The framing an agent READS must agree with what the renderer EMITS.

    ``_render_commons_entry`` was corrected to say ``relevance``, but this
    shared disposition still described "a confidence score" and told the agent
    to weigh "a low-confidence" entry lightly. That is instructional prompt
    text, so leaving it stated the conflation this AD exists to remove more
    directly than the entry ever did -- an agent repeating the label would have
    been repeating the system's own error.
    """
    assert "relevance" in _COMMONS_DISPOSITION
    assert "confidence" not in _COMMONS_DISPOSITION
    assert "low-confidence" not in _COMMONS_DISPOSITION


def test_disposition_announces_exactly_the_fields_the_marker_emits() -> None:
    """THE CROSSING TEST for Section 1: framing and renderer, one assertion.

    Each half can be individually correct while the pair contradicts -- which
    is precisely what happened. Pinning both against one rendered entry is what
    stops them drifting apart again.
    """
    out = _render_commons_entry(
        _result(
            score=0.9,
            metadata={"timestamp": 0.0, "frontmatter": {"author": "Anvil"}},
        )
    )
    for promised in ("tier", "relevance", "author", "age"):
        assert promised in _COMMONS_DISPOSITION, promised
    assert "[ship's records]" in out          # source tier
    assert "relevance 0.90" in out            # relevance score
    assert "by Anvil" in out                  # author
    assert "ago" in out                       # age


# =========================================================================== #
# 3-7. author on the Oracle format path (Section 2)                            #
# =========================================================================== #


@pytest.mark.asyncio
async def test_oracle_path_renders_the_author(monkeypatch) -> None:
    svc = _oracle_with([])
    results = [
        _result(metadata={"path": "notebooks/Anvil/x.md", "frontmatter": {"author": "Anvil"}})
    ]

    async def _query(*a: Any, **k: Any) -> list[OracleResult]:
        return results

    monkeypatch.setattr(svc, "query", _query)
    out = await svc.query_formatted("coolant")

    assert "by Anvil" in out


@pytest.mark.asyncio
async def test_oracle_path_renders_nothing_when_the_author_is_absent(monkeypatch) -> None:
    """Byte-identical for every tier that carries no author. No ``by ?``, no
    ``by unknown`` -- a fabricated placeholder byline IS the defect."""
    svc = _oracle_with([])
    with_author = [
        _result(metadata={"path": "p.md", "frontmatter": {"author": "Anvil"}})
    ]
    without = [_result(metadata={"path": "p.md", "frontmatter": {"author": "   "}})]
    missing = [_result(metadata={"path": "p.md", "frontmatter": {"title": "t"}})]

    async def _q(batch):
        async def _inner(*a: Any, **k: Any) -> list[OracleResult]:
            return batch
        return _inner

    monkeypatch.setattr(svc, "query", await _q(with_author))
    positive = await svc.query_formatted("coolant")
    assert "by Anvil" in positive, "probe never reached the render branch"

    monkeypatch.setattr(svc, "query", await _q(without))
    blank = await svc.query_formatted("coolant")

    monkeypatch.setattr(svc, "query", await _q(missing))
    absent = await svc.query_formatted("coolant")

    assert "by " not in blank
    assert "by " not in absent
    # Byte-identity: an empty author renders exactly what a missing key does.
    assert blank == absent


@pytest.mark.asyncio
async def test_oracle_path_is_byte_identical_when_frontmatter_key_is_absent(
    monkeypatch,
) -> None:
    svc = _oracle_with([])

    async def _q(batch):
        async def _inner(*a: Any, **k: Any) -> list[OracleResult]:
            return batch
        return _inner

    monkeypatch.setattr(svc, "query", await _q([_result(metadata={"path": "p.md"})]))
    no_key = await svc.query_formatted("coolant")

    monkeypatch.setattr(
        svc, "query", await _q([_result(metadata={"path": "p.md", "frontmatter": {}})]),
    )
    empty_fm = await svc.query_formatted("coolant")

    assert "by " not in no_key
    assert no_key == empty_fm
    assert "p.md" in no_key  # the renderer really ran


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", None, [], 0, "Anvil", 17])
async def test_oracle_path_does_not_raise_on_a_non_dict_frontmatter(
    monkeypatch, bad: Any,
) -> None:
    """``isinstance(fm, dict)`` is load-bearing: this renderer is reached by
    tiers that never set the key and by the archive path, which puts a bare
    ``author`` string outside any frontmatter. A ``.get`` on a non-dict is an
    AttributeError inside a formatter that currently cannot raise."""
    svc = _oracle_with([])
    results = [_result(metadata={"path": "p.md", "frontmatter": bad})]

    async def _query(*a: Any, **k: Any) -> list[OracleResult]:
        return results

    monkeypatch.setattr(svc, "query", _query)
    out = await svc.query_formatted("coolant")

    assert "by " not in out
    assert "p.md" in out


@pytest.mark.asyncio
async def test_oracle_path_keeps_score_label_and_path_alongside_the_author(
    monkeypatch,
) -> None:
    """Section 1 must not leak here. ``oracle_service`` already said ``score:``
    and that word is correct -- changing a correct line to match a wrong one is
    how the mislabel would propagate."""
    svc = _oracle_with([])
    results = [
        _result(
            score=0.77,
            metadata={"path": "notebooks/Anvil/x.md", "frontmatter": {"author": "Anvil"}},
        )
    ]

    async def _query(*a: Any, **k: Any) -> list[OracleResult]:
        return results

    monkeypatch.setattr(svc, "query", _query)
    out = await svc.query_formatted("coolant")

    assert "score: 0.77" in out
    assert "by Anvil" in out
    assert "notebooks/Anvil/x.md" in out
    assert "relevance" not in out


# =========================================================================== #
# 8-11. author on the crew-executor path (Section 3)                           #
# =========================================================================== #


def test_crew_marker_carries_the_author() -> None:
    out = _render_commons_entry(
        _result(metadata={"frontmatter": {"author": "Anvil"}})
    )
    assert "by Anvil" in out


def test_crew_marker_without_an_author_differs_only_by_the_corrected_word() -> None:
    """Pins the byte-identity claim: the no-author rendering changed by exactly
    one word, ``confidence`` -> ``relevance``, and nothing else."""
    out = _render_commons_entry(_result(score=0.9, content="body text"))
    assert out == "- [ship's records] (relevance 0.90) body text"
    assert out.replace("relevance", "confidence") == (
        "- [ship's records] (confidence 0.90) body text"
    )


@pytest.mark.parametrize("bad", [None, "", [], 0, "Anvil", 17])
def test_crew_marker_does_not_raise_on_non_dict_metadata_or_frontmatter(bad: Any) -> None:
    positive = _render_commons_entry(
        _result(metadata={"frontmatter": {"author": "Anvil"}})
    )
    assert "by Anvil" in positive, "probe never reached the render branch"

    assert "by " not in _render_commons_entry(_result(metadata=bad))
    assert "by " not in _render_commons_entry(_result(metadata={"frontmatter": bad}))


@pytest.mark.parametrize(
    "frontmatter", [{}, {"title": "t"}, {"author": ""}, {"author": "   "}, {"author": None}],
)
def test_crew_marker_never_fabricates_a_placeholder_byline(frontmatter: Any) -> None:
    """A dict frontmatter that carries no usable author must append NOTHING.

    Not ``by ?``, not ``by unknown``, not ``by anonymous`` -- an invented byline
    is this AD's defect running in the opposite direction, and it is the one
    shape the non-dict tests above cannot reach (they stop at the ``type(fm) is
    dict`` guard before the author is ever read).
    """
    positive = _render_commons_entry(
        _result(metadata={"frontmatter": {"author": "Anvil"}})
    )
    assert "by Anvil" in positive, "probe never reached the author branch"

    out = _render_commons_entry(_result(metadata={"frontmatter": frontmatter}))
    assert "by " not in out
    assert "unknown" not in out
    assert out == "- [ship's records] (relevance 0.90) Coolant resonance peaks at 4.2 kHz."


def test_crew_marker_survives_entry_truncation_with_the_author_intact() -> None:
    """``_MAX_ENTRY_CHARS`` is 400 and the docstring states the marker "is never
    the part that gets cut". The author is now part of the marker."""
    out = _render_commons_entry(
        _result(
            content="z" * 5000,
            metadata={"frontmatter": {"author": "Anvil"}},
        )
    )
    assert len(out) <= _MAX_ENTRY_CHARS
    assert "by Anvil" in out
    assert "relevance 0.90" in out


# =========================================================================== #
# 12-13. the regression this AD exists to prevent -- crossing the seam         #
# =========================================================================== #


@pytest.mark.asyncio
async def test_two_authors_render_distinct_bylines_over_the_oracle_path(
    monkeypatch,
) -> None:
    """THE CROSSING TEST for the Oracle path.

    The retrieval half and the render half each working separately is exactly
    what shipped this defect, so the producer here is the REAL
    ``_query_records_semantic`` -- its output objects are handed straight to
    the real ``query_formatted``. Nothing hand-builds the frontmatter.
    """
    svc = _oracle_with([
        _row(author="Anvil", path="notebooks/Anvil/a.md", snippet="Entry A."),
        _row(author="Sable", path="notebooks/Sable/b.md", snippet="Entry B."),
    ])

    produced = await svc._query_records_semantic("coolant", k=5)
    assert [r.metadata["frontmatter"]["author"] for r in produced] == ["Anvil", "Sable"]

    async def _query(*a: Any, **k: Any) -> list[OracleResult]:
        return produced

    monkeypatch.setattr(svc, "query", _query)
    out = await svc.query_formatted("coolant")

    assert "by Anvil" in out
    assert "by Sable" in out
    # Each byline sits on its own entry, not smeared across both.
    line_a = next(ln for ln in out.splitlines() if "Entry A." in ln)
    line_b = next(ln for ln in out.splitlines() if "Entry B." in ln)
    assert "by Anvil" in line_a and "by Sable" not in line_a
    assert "by Sable" in line_b and "by Anvil" not in line_b


@pytest.mark.asyncio
async def test_two_authors_render_distinct_bylines_over_the_crew_path() -> None:
    """THE CROSSING TEST for the crew path, same real producer."""
    svc = _oracle_with([
        _row(author="Anvil", path="notebooks/Anvil/a.md", snippet="Entry A."),
        _row(author="Sable", path="notebooks/Sable/b.md", snippet="Entry B."),
    ])

    produced = await svc._query_records_semantic("coolant", k=5)
    rendered = [_render_commons_entry(r) for r in produced]

    assert "by Anvil" in rendered[0] and "by Sable" not in rendered[0]
    assert "by Sable" in rendered[1] and "by Anvil" not in rendered[1]


def test_decode_record_frontmatter_still_degrades_to_a_dict() -> None:
    """The guard the renderers rely on. Not changed by this AD -- pinned so a
    later change to it cannot silently reintroduce the AttributeError."""
    assert _decode_record_frontmatter("") == {}
    assert _decode_record_frontmatter(None) == {}
    assert _decode_record_frontmatter("[1,2]") == {}
    assert _decode_record_frontmatter('{"author": "Anvil"}') == {"author": "Anvil"}
