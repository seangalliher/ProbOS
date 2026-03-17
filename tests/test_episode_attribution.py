"""Tests for AD-295b: Episode Attribution Enrichment."""

from __future__ import annotations

import json

import pytest

from probos.types import Episode


class TestEpisodeAttribution:
    def test_episode_stores_shapley(self):
        """Episode carries Shapley attribution values."""
        ep = Episode(
            user_input="test request",
            shapley_values={"agent-a": 0.6, "agent-b": 0.4},
        )
        assert ep.shapley_values == {"agent-a": 0.6, "agent-b": 0.4}

    def test_episode_stores_trust_deltas(self):
        """Episode carries trust deltas."""
        deltas = [
            {"agent_id": "agent-a", "old": 0.5, "new": 0.6, "weight": 0.8},
            {"agent_id": "agent-b", "old": 0.5, "new": 0.45, "weight": 1.0},
        ]
        ep = Episode(
            user_input="test request",
            trust_deltas=deltas,
        )
        assert len(ep.trust_deltas) == 2
        assert ep.trust_deltas[0]["agent_id"] == "agent-a"
        assert ep.trust_deltas[1]["new"] == 0.45

    def test_episode_serialization_roundtrip(self):
        """Episode with all new fields survives serialize-deserialize."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = Episode(
            id="ep-test-001",
            timestamp=1234567890.0,
            user_input="Hello ProbOS",
            dag_summary={"node_count": 2, "intent_types": ["read_file"]},
            outcomes=[{"intent": "read_file", "success": True, "status": "completed"}],
            reflection="All went well.",
            agent_ids=["agent-1", "agent-2"],
            duration_ms=150.5,
            shapley_values={"agent-1": 0.7, "agent-2": 0.3},
            trust_deltas=[
                {"agent_id": "agent-1", "old": 0.5, "new": 0.58, "weight": 0.7},
            ],
        )

        metadata = EpisodicMemory._episode_to_metadata(ep)

        # Verify new fields are serialized
        assert "shapley_values_json" in metadata
        assert "trust_deltas_json" in metadata
        assert json.loads(metadata["shapley_values_json"]) == {"agent-1": 0.7, "agent-2": 0.3}

        # Roundtrip
        restored = EpisodicMemory._metadata_to_episode(
            doc_id=ep.id, document=ep.user_input, metadata=metadata,
        )
        assert restored.shapley_values == ep.shapley_values
        assert restored.trust_deltas == ep.trust_deltas
        assert restored.agent_ids == ep.agent_ids
        assert restored.duration_ms == ep.duration_ms

    def test_episode_defaults_backward_compatible(self):
        """Old episodes without new fields deserialize with defaults."""
        from probos.cognitive.episodic import EpisodicMemory

        # Simulate old metadata without shapley/trust fields
        old_metadata = {
            "timestamp": 1234567890.0,
            "intent_type": "read_file",
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 100.0,
        }
        restored = EpisodicMemory._metadata_to_episode(
            doc_id="old-ep", document="old request", metadata=old_metadata,
        )
        assert restored.shapley_values == {}
        assert restored.trust_deltas == []
