from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from probos.cognitive.provenance import (
    ProvenanceEnvelope,
    ProvenanceTag,
    STALE_AFTER_SECONDS,
    compute_content_hash,
    query_with_provenance,
)
from probos.events import EventType


def test_provenance_tag_creation() -> None:
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=123.0,
        relevance=0.82,
        content_hash="abcdef12",
        metadata={"episode_id": "ep-1"},
    )

    assert tag.source_tier == "episodic"
    assert tag.retrieval_timestamp == 123.0
    assert tag.relevance == 0.82
    assert tag.content_hash == "abcdef12"
    assert tag.metadata == {"episode_id": "ep-1"}


def test_provenance_tag_age() -> None:
    # BF-950: built from ``retrieval_timestamp`` and asserted its age, which was
    # the defect: the retrieval is the call that renders the marker, so that age
    # was always about zero. The age is the content's own write time now, and
    # absent when the tier records none.
    tag = ProvenanceTag(
        source_tier="records",
        retrieval_timestamp=time.time(),
        relevance=0.7,
        content_hash="abcdef12",
        content_timestamp=time.time() - 90,
    )
    untimed = ProvenanceTag(
        source_tier="graph",
        retrieval_timestamp=time.time() - 600,
        relevance=0.7,
        content_hash="abcdef12",
    )

    assert tag.age_seconds >= 90
    assert untimed.age_seconds is None


def test_provenance_tag_staleness() -> None:
    # BF-950: was STALE from a retrieval 600 s back (the 300 s threshold on the
    # retrieval's clock). Staleness is the content's age past STALE_AFTER_SECONDS.
    tag = ProvenanceTag(
        source_tier="operational",
        retrieval_timestamp=time.time() - 600,
        relevance=0.7,
        content_hash="abcdef12",
        content_timestamp=time.time() - STALE_AFTER_SECONDS - 60,
    )

    assert tag.is_stale is True


def test_provenance_tag_format_inline() -> None:
    # BF-950: the age comes from ``content_timestamp``; without one the marker has no age.
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=time.time(),
        relevance=0.82,
        content_hash="abcdef12",
        content_timestamp=time.time(),
    )

    marker = tag.format_inline()

    assert marker.startswith("[source:episodic relevance:0.82 age:")
    assert marker.endswith("s]")


def test_provenance_tag_stale_marker() -> None:
    # BF-950: was STALE from a retrieval 600 s back; STALE is the content's age past STALE_AFTER_SECONDS.
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=time.time() - 600,
        relevance=0.82,
        content_hash="abcdef12",
        content_timestamp=time.time() - STALE_AFTER_SECONDS - 60,
    )

    assert "STALE" in tag.format_inline()


def test_compute_content_hash() -> None:
    first = compute_content_hash("same content")
    second = compute_content_hash("same content")
    different = compute_content_hash("different content")

    assert first == second
    assert first != different


def test_compute_content_hash_length() -> None:
    assert len(compute_content_hash("content")) == 8


def test_provenance_envelope_render() -> None:
    envelope = ProvenanceEnvelope(
        content="retrieved fact",
        tag=ProvenanceTag(
            source_tier="records",
            retrieval_timestamp=time.time(),
            relevance=0.91,
            content_hash="abcdef12",
            # BF-950: the rendered age is the content's; without a write time there is none.
            content_timestamp=time.time(),
        ),
    )

    rendered = envelope.render()

    assert rendered.startswith("[source:records relevance:0.91 age:")
    assert rendered.endswith("\nretrieved fact")


def test_provenance_envelope_from_oracle_result() -> None:
    result = _OracleResult(
        source_tier="episodic",
        content="episode summary",
        score=0.76,
        metadata={"episode_id": "ep-1"},
    )

    envelope = ProvenanceEnvelope.from_oracle_result(result)

    assert envelope.content == "episode summary"
    assert envelope.tag.source_tier == "episodic"
    assert envelope.tag.relevance == 0.76
    assert envelope.tag.metadata == {"episode_id": "ep-1"}


def test_context_provenance_event_type() -> None:
    assert (
        EventType.CONTEXT_PROVENANCE_INJECTED.value
        == "context_provenance_injected"
    )


@pytest.mark.asyncio
async def test_query_with_provenance() -> None:
    oracle = _FakeOracle()

    envelopes = await query_with_provenance(
        oracle,
        query_text="warp core",
        agent_id="agent-1",
        intent_type="diagnose",
        k_per_tier=2,
        tiers=["episodic"],
    )

    assert oracle.calls == [
        {
            "query_text": "warp core",
            "agent_id": "agent-1",
            "intent_type": "diagnose",
            "k_per_tier": 2,
            "tiers": ["episodic"],
        }
    ]
    assert len(envelopes) == 1
    assert isinstance(envelopes[0], ProvenanceEnvelope)
    assert envelopes[0].tag.source_tier == "episodic"
    assert envelopes[0].tag.relevance == 0.84


@dataclass
class _OracleResult:
    source_tier: str
    content: str
    score: float
    metadata: dict[str, Any]


class _FakeOracle:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def query(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 5,
        tiers: list[str] | None = None,
    ) -> list[_OracleResult]:
        self.calls.append(
            {
                "query_text": query_text,
                "agent_id": agent_id,
                "intent_type": intent_type,
                "k_per_tier": k_per_tier,
                "tiers": tiers,
            }
        )
        return [
            _OracleResult(
                source_tier="episodic",
                content="warp core diagnostic",
                score=0.84,
                metadata={"episode_id": "ep-1"},
            )
        ]
