"""AD-493: Novelty Gate — Semantic Observation Dedup.

Tests cover:
- Core novelty detection (6 tests)
- Per-agent isolation (2 tests)
- Decay (3 tests)
- Ring buffer (2 tests)
- Bypass conditions (3 tests)
- Record/check separation (2 tests)
- Stats and management (2 tests)
- Pipeline wiring (1 test)
"""

from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.novelty_gate import NoveltyGate, NoveltyVerdict


# ── Helpers ──────────────────────────────────────────────────────

def _make_vec(angle_degrees: float, dims: int = 10) -> list[float]:
    """Create a simple test embedding vector with controlled cosine similarity."""
    vec = [0.0] * dims
    vec[0] = math.cos(math.radians(angle_degrees))
    vec[1] = math.sin(math.radians(angle_degrees))
    return vec


LONG_TEXT = "This is a sufficiently long observation text for testing " * 3  # >80 chars


def _make_gate(**kwargs) -> NoveltyGate:
    """Create a NoveltyGate with test-friendly defaults."""
    defaults = {
        "similarity_threshold": 0.82,
        "max_fingerprints_per_agent": 50,
        "decay_hours": 24.0,
        "min_text_length": 80,
    }
    defaults.update(kwargs)
    return NoveltyGate(**defaults)


# ── Core novelty detection (6 tests) ────────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_first_observation_always_novel(mock_embed):
    """No prior fingerprints → novel."""
    mock_embed.return_value = _make_vec(0)
    gate = _make_gate()

    verdict = gate.check("agent-1", LONG_TEXT)
    assert verdict.is_novel
    assert verdict.reason == "no_prior_observations"


@patch("probos.knowledge.embeddings.embed_text")
def test_identical_observation_blocked(mock_embed):
    """Same embedding twice → not novel (sim=1.0)."""
    mock_embed.return_value = _make_vec(0)
    gate = _make_gate()

    gate.record("agent-1", LONG_TEXT)
    verdict = gate.check("agent-1", LONG_TEXT)

    assert not verdict.is_novel
    assert verdict.similarity == 1.0
    assert verdict.reason == "semantic_duplicate"


@patch("probos.knowledge.embeddings.embed_text")
def test_similar_observation_above_threshold_blocked(mock_embed):
    """Embedding with sim > 0.82 → not novel."""
    gate = _make_gate()

    # Record at angle 0
    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT)

    # Check at angle 10 → cos(10°) ≈ 0.985 > 0.82
    mock_embed.return_value = _make_vec(10)
    verdict = gate.check("agent-1", LONG_TEXT + " variant")

    assert not verdict.is_novel
    assert verdict.similarity > 0.82


@patch("probos.knowledge.embeddings.embed_text")
def test_different_observation_below_threshold_passes(mock_embed):
    """Embedding with sim < 0.82 → novel."""
    gate = _make_gate()

    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT)

    # cos(60°) ≈ 0.5 < 0.82
    mock_embed.return_value = _make_vec(60)
    verdict = gate.check("agent-1", LONG_TEXT + " different topic")

    assert verdict.is_novel
    assert verdict.similarity < 0.82


@patch("probos.knowledge.embeddings.embed_text")
def test_multiple_fingerprints_checks_all(mock_embed):
    """Third observation similar to first (not second) → blocked."""
    gate = _make_gate()

    # Record two different topics
    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT + " topic A")

    mock_embed.return_value = _make_vec(90)
    gate.record("agent-1", LONG_TEXT + " topic B")

    # Check something similar to topic A (angle 5 → cos ≈ 0.996)
    mock_embed.return_value = _make_vec(5)
    verdict = gate.check("agent-1", LONG_TEXT + " rehash of topic A")

    assert not verdict.is_novel


@patch("probos.knowledge.embeddings.embed_text")
def test_verdict_includes_matched_preview(mock_embed):
    """Non-novel verdict has matched_preview from the matching fingerprint."""
    gate = _make_gate()

    original = "This is the original observation text that will be fingerprinted and matched against later checks"
    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", original)

    mock_embed.return_value = _make_vec(5)  # Very similar
    verdict = gate.check("agent-1", LONG_TEXT)

    assert not verdict.is_novel
    assert verdict.matched_preview == original[:100]


# ── Per-agent isolation (2 tests) ───────────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_different_agents_independent(mock_embed):
    """Agent A's fingerprint does not block Agent B."""
    gate = _make_gate()

    mock_embed.return_value = _make_vec(0)
    gate.record("agent-A", LONG_TEXT)

    # Same embedding for agent B — should be novel (no fingerprints for B)
    verdict = gate.check("agent-B", LONG_TEXT)
    assert verdict.is_novel
    assert verdict.reason == "no_prior_observations"


@patch("probos.knowledge.embeddings.embed_text")
def test_same_agent_accumulates(mock_embed):
    """Multiple observations build up agent's fingerprint set."""
    gate = _make_gate()

    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT + " first")

    mock_embed.return_value = _make_vec(90)
    gate.record("agent-1", LONG_TEXT + " second")

    assert len(gate._fingerprints["agent-1"]) == 2


# ── Decay (3 tests) ────────────────────────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_old_fingerprints_evicted(mock_embed):
    """Fingerprint older than decay_hours is evicted."""
    gate = _make_gate(decay_hours=24.0)

    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT)

    # Age the fingerprint past decay window
    gate._fingerprints["agent-1"][0].timestamp -= (25 * 3600)

    verdict = gate.check("agent-1", LONG_TEXT)
    assert verdict.is_novel  # Fingerprint evicted


@patch("probos.knowledge.embeddings.embed_text")
def test_decay_zero_no_eviction(mock_embed):
    """With decay_hours=0, old fingerprints persist."""
    gate = _make_gate(decay_hours=0)

    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT)

    # Age it way back
    gate._fingerprints["agent-1"][0].timestamp -= (999 * 3600)

    verdict = gate.check("agent-1", LONG_TEXT)
    assert not verdict.is_novel  # Still blocked — no decay


@patch("probos.knowledge.embeddings.embed_text")
def test_recent_fingerprints_survive_eviction(mock_embed):
    """Only stale fingerprints are evicted, recent ones remain."""
    gate = _make_gate(decay_hours=24.0)

    # Record two observations
    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT + " old topic")

    mock_embed.return_value = _make_vec(90)
    gate.record("agent-1", LONG_TEXT + " new topic")

    # Age only the first fingerprint
    gate._fingerprints["agent-1"][0].timestamp -= (25 * 3600)

    # Check something similar to old topic — should pass (evicted)
    mock_embed.return_value = _make_vec(5)
    verdict = gate.check("agent-1", LONG_TEXT + " rehash old")
    assert verdict.is_novel

    # Check something similar to new topic — should block (still fresh)
    mock_embed.return_value = _make_vec(85)
    verdict2 = gate.check("agent-1", LONG_TEXT + " rehash new")
    assert not verdict2.is_novel


# ── Ring buffer (2 tests) ──────────────────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_ring_buffer_evicts_oldest(mock_embed):
    """After max_fingerprints_per_agent, oldest is evicted."""
    gate = _make_gate(max_fingerprints_per_agent=3)

    for i in range(4):
        mock_embed.return_value = _make_vec(i * 30)
        gate.record("agent-1", LONG_TEXT + f" observation {i}")

    assert len(gate._fingerprints["agent-1"]) == 3


@patch("probos.knowledge.embeddings.embed_text")
def test_evicted_topic_becomes_novel_again(mock_embed):
    """After ring buffer eviction, the evicted topic is novel again."""
    gate = _make_gate(max_fingerprints_per_agent=2)

    # Record topic at angle 0 (will be evicted)
    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT + " first topic")

    # Record two more (evicts the first)
    mock_embed.return_value = _make_vec(60)
    gate.record("agent-1", LONG_TEXT + " second topic")
    mock_embed.return_value = _make_vec(120)
    gate.record("agent-1", LONG_TEXT + " third topic")

    # Check topic at angle 0 — should be novel (evicted)
    mock_embed.return_value = _make_vec(0)
    verdict = gate.check("agent-1", LONG_TEXT + " first topic again")
    assert verdict.is_novel


# ── Bypass conditions (3 tests) ────────────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_short_text_bypasses_gate(mock_embed):
    """Text shorter than min_text_length is always novel."""
    gate = _make_gate(min_text_length=80)

    verdict = gate.check("agent-1", "short")
    assert verdict.is_novel
    assert verdict.reason == "below_min_length"
    mock_embed.assert_not_called()


def test_embedding_failure_passes_as_novel():
    """If embed_text raises, observation passes (fail-open)."""
    gate = _make_gate()

    with patch("probos.knowledge.embeddings.embed_text", side_effect=RuntimeError("ONNX failed")):
        verdict = gate.check("agent-1", LONG_TEXT)

    assert verdict.is_novel
    assert verdict.reason == "embedding_failed"


def test_empty_embedding_passes_as_novel():
    """If embed_text returns empty list, observation passes."""
    gate = _make_gate()

    with patch("probos.knowledge.embeddings.embed_text", return_value=[]):
        verdict = gate.check("agent-1", LONG_TEXT)

    assert verdict.is_novel
    assert verdict.reason == "empty_embedding"


# ── Record/check separation (2 tests) ──────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_check_does_not_record(mock_embed):
    """Calling check() alone does not add a fingerprint."""
    mock_embed.return_value = _make_vec(0)
    gate = _make_gate()

    gate.check("agent-1", LONG_TEXT)
    assert "agent-1" not in gate._fingerprints or len(gate._fingerprints.get("agent-1", [])) == 0


@patch("probos.knowledge.embeddings.embed_text")
def test_record_then_similar_check_blocks(mock_embed):
    """record() with text A, then check() with similar text B → blocked."""
    gate = _make_gate()

    # Record at angle 0
    mock_embed.return_value = _make_vec(0)
    gate.record("agent-1", LONG_TEXT + " original observation")

    # Check at angle 8 → cos(8°) ≈ 0.990 > 0.82
    mock_embed.return_value = _make_vec(8)
    verdict = gate.check("agent-1", LONG_TEXT + " rephrased observation")

    assert not verdict.is_novel
    assert verdict.reason == "semantic_duplicate"


# ── Stats and management (2 tests) ─────────────────────────────

@patch("probos.knowledge.embeddings.embed_text")
def test_get_stats(mock_embed):
    """Returns correct counts after checks/blocks/bypasses."""
    mock_embed.return_value = _make_vec(0)
    gate = _make_gate()

    # 1 bypass (short text)
    gate.check("agent-1", "short")

    # 1 novel check (no prior fingerprints)
    gate.check("agent-1", LONG_TEXT)

    # Record, then check identical → 1 block
    gate.record("agent-1", LONG_TEXT)
    gate.check("agent-1", LONG_TEXT)

    stats = gate.get_stats()
    assert stats["checks"] == 3
    assert stats["blocks"] == 1
    assert stats["bypasses"] == 1
    assert stats["agents_tracked"] == 1
    assert stats["total_fingerprints"] == 1
    assert stats["threshold"] == 0.82


@patch("probos.knowledge.embeddings.embed_text")
def test_clear_agent(mock_embed):
    """clear_agent() removes fingerprints, same topic becomes novel again."""
    mock_embed.return_value = _make_vec(0)
    gate = _make_gate()

    gate.record("agent-1", LONG_TEXT)
    verdict1 = gate.check("agent-1", LONG_TEXT)
    assert not verdict1.is_novel

    gate.clear_agent("agent-1")
    verdict2 = gate.check("agent-1", LONG_TEXT)
    assert verdict2.is_novel


# ── Pipeline wiring (1 test) ───────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_records_fingerprint_after_post():
    """Pipeline calls novelty_gate.record() after successful create_post."""
    from probos.ward_room_pipeline import WardRoomPostPipeline

    ward_room = MagicMock()
    ward_room.create_post = AsyncMock()
    router = MagicMock()
    router.extract_endorsements = MagicMock(return_value=("test response body text", []))
    router.record_agent_response = MagicMock()
    router.record_round_post = MagicMock()
    router.update_cooldown = MagicMock()
    router.extract_recreation_commands = AsyncMock(return_value="test response body text")

    mock_gate = MagicMock()
    mock_gate.check = MagicMock(return_value=NoveltyVerdict(
        is_novel=True, similarity=0.0, reason="novel",
    ))
    mock_gate.record = MagicMock()

    pipeline = WardRoomPostPipeline(
        ward_room=ward_room,
        ward_room_router=router,
        proactive_loop=None,
        trust_network=None,
        callsign_registry=None,
        config=MagicMock(),
        runtime=None,
        novelty_gate=mock_gate,
    )

    agent = MagicMock()
    agent.id = "agent-1"
    agent.agent_type = "test_agent"

    result = await pipeline.process_and_post(
        agent=agent,
        response_text="test response body text",
        thread_id="thread_00000001",
        event_type="ward_room_post_created",
    )

    assert result is True
    mock_gate.record.assert_called_once_with("agent-1", "test response body text")
