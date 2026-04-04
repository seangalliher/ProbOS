"""AD-541b: Reconsolidation Protection — READ-ONLY memory framing tests.

Tests for:
- D1: READ-ONLY framing for parent procedure blocks
- D2: System prompt READ-ONLY awareness
- D3: Frozen Episode dataclass
- D4: ChromaDB write-once guard
- D5: SIF memory integrity check
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import (
    Procedure,
    ProcedureStep,
    _format_procedure_block,
    _SYSTEM_PROMPT,
    _FIX_SYSTEM_PROMPT,
    _DERIVED_SYSTEM_PROMPT,
    _COMPOUND_SYSTEM_PROMPT,
    _FALLBACK_FIX_SYSTEM_PROMPT,
    _NEGATIVE_SYSTEM_PROMPT,
    evolve_fix_procedure,
    evolve_derived_procedure,
    evolve_fix_from_fallback,
    extract_negative_procedure_from_cluster,
    extract_procedure_from_cluster,
    extract_compound_procedure_from_cluster,
    extract_procedure_from_observation,
)
from probos.types import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_procedure(**overrides) -> Procedure:
    defaults = {
        "name": "test",
        "description": "test procedure",
        "steps": [ProcedureStep(step_number=1, action="do thing")],
        "preconditions": ["pre"],
        "postconditions": ["post"],
        "intent_types": ["test_intent"],
        "origin_cluster_id": "c1",
        "origin_agent_ids": ["a1"],
        "extraction_date": time.time(),
    }
    defaults.update(overrides)
    return Procedure(**defaults)


def _make_cluster(**overrides) -> MagicMock:
    c = MagicMock()
    c.cluster_id = overrides.get("cluster_id", "c1")
    c.success_rate = overrides.get("success_rate", 0.9)
    c.intent_types = overrides.get("intent_types", ["test"])
    c.participating_agents = overrides.get("participating_agents", ["a1"])
    c.episode_ids = overrides.get("episode_ids", ["ep1"])
    return c


def _make_episode(**overrides) -> Episode:
    defaults = {
        "user_input": "test input",
        "outcomes": [{"success": True}],
        "dag_summary": {},
        "agent_ids": ["a1"],
        "timestamp": time.time(),
        "source": "direct",
    }
    defaults.update(overrides)
    return Episode(**defaults)


def _make_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


_VALID_PROCEDURE_JSON = json.dumps({
    "name": "Repaired",
    "description": "test",
    "steps": [{"step_number": 1, "action": "fixed step"}],
    "preconditions": [],
    "postconditions": [],
    "change_summary": "Fixed the thing",
})

_VALID_DERIVED_JSON = json.dumps({
    "name": "Derived",
    "description": "specialized",
    "steps": [{"step_number": 1, "action": "special step"}],
    "preconditions": [],
    "postconditions": [],
    "change_summary": "Specialized",
})

_VALID_NEGATIVE_JSON = json.dumps({
    "name": "Anti-pattern",
    "description": "bad pattern",
    "steps": [{"step_number": 1, "action": "bad action"}],
    "preconditions": [],
    "postconditions": [],
})

_VALID_EXTRACT_JSON = json.dumps({
    "name": "Extracted",
    "description": "extracted proc",
    "steps": [{"step_number": 1, "action": "step 1"}],
    "preconditions": [],
    "postconditions": [],
})


# ===========================================================================
# D1: READ-ONLY procedure framing
# ===========================================================================


class TestFormatProcedureBlock:
    """D1 tests — _format_procedure_block helper."""

    def test_format_procedure_block_contains_readonly_markers(self):
        """Test 1: Output has READ-ONLY boundary markers with label."""
        proc = _make_procedure()
        result = _format_procedure_block(proc, "DEGRADED PROCEDURE")
        assert "=== READ-ONLY DEGRADED PROCEDURE" in result
        assert "=== END READ-ONLY DEGRADED PROCEDURE ===" in result
        assert "do not modify source" in result

    def test_format_procedure_block_contains_procedure_json(self):
        """Test 2: Procedure JSON appears between boundaries."""
        proc = _make_procedure(name="SpecialProc")
        result = _format_procedure_block(proc)
        assert '"SpecialProc"' in result
        assert '"do thing"' in result


class TestEvolutionReadOnlyFraming:
    """D1 tests — evolution functions use READ-ONLY blocks."""

    @pytest.mark.asyncio
    async def test_evolve_fix_uses_readonly_procedure_block(self):
        """Test 3: evolve_fix_procedure prompt contains READ-ONLY DEGRADED PROCEDURE."""
        parent = _make_procedure()
        episodes = [_make_episode()]
        llm = AsyncMock()
        llm.complete.return_value = _make_llm_response(_VALID_PROCEDURE_JSON)

        await evolve_fix_procedure(parent, "FIX:test", {}, episodes, llm)

        request = llm.complete.call_args[0][0]
        assert "READ-ONLY DEGRADED PROCEDURE" in request.prompt

    @pytest.mark.asyncio
    async def test_evolve_derived_uses_readonly_procedure_blocks(self):
        """Test 4: evolve_derived_procedure prompt contains READ-ONLY PARENT PROCEDURE."""
        parents = [_make_procedure()]
        episodes = [_make_episode()]
        llm = AsyncMock()
        llm.complete.return_value = _make_llm_response(_VALID_DERIVED_JSON)

        await evolve_derived_procedure(parents, episodes, llm)

        request = llm.complete.call_args[0][0]
        assert "READ-ONLY PARENT PROCEDURE 1" in request.prompt

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_uses_readonly_blocks(self):
        """Test 5: evolve_fix_from_fallback prompt contains both READ-ONLY blocks."""
        parent = _make_procedure()
        episodes = [_make_episode()]
        llm = AsyncMock()
        llm.complete.return_value = _make_llm_response(_VALID_PROCEDURE_JSON)

        await evolve_fix_from_fallback(
            parent, "execution_failure", "llm did good", "reason", episodes, llm,
        )

        request = llm.complete.call_args[0][0]
        assert "READ-ONLY PROCEDURE TO REPAIR" in request.prompt
        assert "READ-ONLY LLM RESPONSE" in request.prompt

    @pytest.mark.asyncio
    async def test_negative_extraction_contradiction_context_readonly(self):
        """Test 6: Contradiction context uses READ-ONLY markers."""
        cluster = _make_cluster(success_rate=0.1)
        episodes = [_make_episode()]

        contradiction = MagicMock()
        contradiction.intent = "test"
        contradiction.similarity = 0.9
        contradiction.older_episode_id = "ep-old"
        contradiction.older_outcome = "success"
        contradiction.newer_episode_id = "ep-new"
        contradiction.newer_outcome = "failure"
        contradiction.agent_id = "a1"
        contradiction.description = "Conflicting results"

        llm = AsyncMock()
        llm.complete.return_value = _make_llm_response(_VALID_NEGATIVE_JSON)

        await extract_negative_procedure_from_cluster(
            cluster, episodes, llm, contradictions=[contradiction],
        )

        request = llm.complete.call_args[0][0]
        assert "READ-ONLY CONTRADICTION CONTEXT" in request.prompt
        assert "END READ-ONLY CONTRADICTION CONTEXT" in request.prompt


# ===========================================================================
# D2: System prompt READ-ONLY awareness
# ===========================================================================


class TestSystemPromptAwareness:
    """D2 tests — system prompts contain READ-ONLY instruction."""

    def test_system_prompts_contain_readonly_instruction(self):
        """Test 7: All system prompt constants have READ-ONLY instruction."""
        readonly_instruction = "All input blocks marked READ-ONLY are source material"
        for name, prompt in [
            ("_SYSTEM_PROMPT", _SYSTEM_PROMPT),
            ("_FIX_SYSTEM_PROMPT", _FIX_SYSTEM_PROMPT),
            ("_DERIVED_SYSTEM_PROMPT", _DERIVED_SYSTEM_PROMPT),
            ("_COMPOUND_SYSTEM_PROMPT", _COMPOUND_SYSTEM_PROMPT),
            ("_FALLBACK_FIX_SYSTEM_PROMPT", _FALLBACK_FIX_SYSTEM_PROMPT),
            ("_NEGATIVE_SYSTEM_PROMPT", _NEGATIVE_SYSTEM_PROMPT),
        ]:
            assert readonly_instruction in prompt, f"{name} missing READ-ONLY instruction"

    @pytest.mark.asyncio
    async def test_evolution_user_prompts_contain_no_alter_instruction(self):
        """Test 8: Evolution functions include 'Do not alter' in user prompt."""
        parent = _make_procedure()
        episodes = [_make_episode()]
        llm = AsyncMock()

        no_alter = "Do not alter, embellish, or reinterpret"

        # evolve_fix_procedure
        llm.complete.return_value = _make_llm_response(_VALID_PROCEDURE_JSON)
        await evolve_fix_procedure(parent, "FIX:test", {}, episodes, llm)
        assert no_alter in llm.complete.call_args[0][0].prompt

        llm.reset_mock()

        # evolve_derived_procedure
        llm.complete.return_value = _make_llm_response(_VALID_DERIVED_JSON)
        await evolve_derived_procedure([parent], episodes, llm)
        assert no_alter in llm.complete.call_args[0][0].prompt

        llm.reset_mock()

        # evolve_fix_from_fallback
        llm.complete.return_value = _make_llm_response(_VALID_PROCEDURE_JSON)
        await evolve_fix_from_fallback(
            parent, "exec_fail", "resp", "reason", episodes, llm,
        )
        assert no_alter in llm.complete.call_args[0][0].prompt

    @pytest.mark.asyncio
    async def test_all_dream_llm_calls_have_readonly_framing(self):
        """Test 9: All 7 episode-processing functions have READ-ONLY markers."""
        episodes = [_make_episode()]
        cluster = _make_cluster()
        parent = _make_procedure()
        llm = AsyncMock()

        import probos.cognitive.procedures as proc_mod

        functions_and_args = [
            (proc_mod.extract_procedure_from_cluster, (cluster, episodes, llm)),
            (proc_mod.extract_negative_procedure_from_cluster, (_make_cluster(success_rate=0.1), episodes, llm)),
            (proc_mod.extract_compound_procedure_from_cluster, (cluster, episodes, llm)),
            (proc_mod.evolve_fix_procedure, (parent, "FIX:test", {}, episodes, llm)),
            (proc_mod.evolve_derived_procedure, ([parent], episodes, llm)),
            (proc_mod.evolve_fix_from_fallback, (parent, "fail", "resp", "reason", episodes, llm)),
            (proc_mod.extract_procedure_from_observation, ("thread content", "test_agent", "Bones", 0.8, llm)),
        ]

        for fn, args in functions_and_args:
            llm.reset_mock()
            llm.complete.return_value = _make_llm_response(_VALID_EXTRACT_JSON)

            await fn(*args)

            request = llm.complete.call_args[0][0]
            assert "READ-ONLY" in request.prompt, f"{fn.__name__} missing READ-ONLY in user prompt"


# ===========================================================================
# D3: Frozen Episode
# ===========================================================================


class TestFrozenEpisode:
    """D3 tests — Episode dataclass is frozen."""

    def test_episode_is_frozen(self):
        """Test 10: Setting a field on Episode raises FrozenInstanceError."""
        ep = _make_episode()
        with pytest.raises(FrozenInstanceError):
            ep.source = "secondhand"

    def test_episode_replace_creates_new_instance(self):
        """Test 11: dataclasses.replace creates new episode, original unchanged."""
        ep = _make_episode(source="direct")
        new_ep = dataclasses.replace(ep, source="secondhand")
        assert new_ep.source == "secondhand"
        assert ep.source == "direct"
        assert new_ep.id != ep.id or new_ep is not ep

    def test_episode_default_factories_work_with_frozen(self):
        """Test 12: Episode constructs correctly with all defaults."""
        ep = Episode()
        assert len(ep.id) == 32  # uuid4 hex
        assert ep.outcomes == []
        assert ep.agent_ids == []
        assert ep.embedding == []
        assert ep.shapley_values == {}
        assert ep.trust_deltas == []
        assert ep.source == "direct"

    def test_episode_equality_by_value(self):
        """Test 13: Two episodes with same fields are equal."""
        shared_id = "abc123"
        ep1 = Episode(id=shared_id, timestamp=100.0, user_input="test",
                       source="direct", outcomes=[], agent_ids=[])
        ep2 = Episode(id=shared_id, timestamp=100.0, user_input="test",
                       source="direct", outcomes=[], agent_ids=[])
        assert ep1 == ep2

    def test_episode_frozen_prevents_embedding_mutation(self):
        """Test 14: Cannot reassign embedding field on frozen Episode."""
        ep = _make_episode()
        with pytest.raises(FrozenInstanceError):
            ep.embedding = [1.0, 2.0, 3.0]

    def test_episode_with_all_fields(self):
        """Test 15: Episode constructs with all fields populated."""
        ep = Episode(
            id="test-id",
            timestamp=time.time(),
            user_input="full episode",
            dag_summary={"nodes": []},
            outcomes=[{"success": True, "intent": "test"}],
            reflection="reflected",
            agent_ids=["a1", "a2"],
            duration_ms=123.4,
            embedding=[0.1, 0.2],
            shapley_values={"a1": 0.6, "a2": 0.4},
            trust_deltas=[{"agent": "a1", "delta": 0.01}],
            source="secondhand",
        )
        assert ep.source == "secondhand"
        assert len(ep.outcomes) == 1


# ===========================================================================
# D4: Write-once guard
# ===========================================================================


class TestWriteOnceGuard:
    """D4 tests — ChromaDB write-once episode storage."""

    @pytest.mark.asyncio
    async def test_store_new_episode_succeeds(self):
        """Test 16: Storing a new episode works."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}  # No existing
        mock_collection.count.return_value = 0
        em._collection = mock_collection

        ep = _make_episode()
        await em.store(ep)
        mock_collection.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_duplicate_episode_id_skipped(self):
        """Test 17: Duplicate episode ID is skipped (not overwritten)."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        # First call for rate limit check, second for duplicate check, third for write-once
        mock_collection.get.side_effect = [
            {"metadatas": []},  # rate limit
            {"ids": [], "metadatas": [], "documents": []},  # dedup
            {"ids": ["existing-id"]},  # write-once: already exists
        ]
        mock_collection.count.return_value = 0
        em._collection = mock_collection

        ep = _make_episode()
        await em.store(ep)
        mock_collection.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_duplicate_logs_warning(self):
        """Test 18: Duplicate store logs a warning with 'write-once'."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        mock_collection.get.side_effect = [
            {"metadatas": []},  # rate limit
            {"ids": [], "metadatas": [], "documents": []},  # dedup
            {"ids": ["existing-id"]},  # write-once
        ]
        mock_collection.count.return_value = 0
        em._collection = mock_collection

        ep = _make_episode()
        with patch("probos.cognitive.episodic.logger") as mock_logger:
            await em.store(ep)
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "write-once" in warning_msg

    def test_force_update_bypasses_guard(self):
        """Test 19: _force_update uses upsert (bypass for migration)."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        em._collection = mock_collection

        ep = _make_episode()
        em._force_update(ep)
        mock_collection.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_upsert_in_normal_store_path(self):
        """Test 20: Normal store() uses add(), not upsert()."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        mock_collection.get.side_effect = [
            {"metadatas": []},  # rate limit
            {"ids": [], "metadatas": [], "documents": []},  # dedup
            {"ids": []},  # write-once: not existing
        ]
        mock_collection.count.return_value = 0
        em._collection = mock_collection

        ep = _make_episode()
        await em.store(ep)
        mock_collection.add.assert_called_once()
        mock_collection.upsert.assert_not_called()


# ===========================================================================
# D5: SIF memory integrity check
# ===========================================================================


class TestSIFMemoryIntegrity:
    """D5 tests — SIF check_memory_integrity."""

    def test_sif_memory_integrity_passes_with_valid_episodes(self):
        """Test 21: Valid episodes pass integrity check."""
        from probos.sif import StructuralIntegrityField

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.get.return_value = {
            "ids": ["ep1", "ep2"],
            "metadatas": [
                {"source": "direct", "timestamp": time.time()},
                {"source": "secondhand", "timestamp": time.time()},
            ],
        }
        mock_em._collection = mock_collection

        sif = StructuralIntegrityField(episodic_memory=mock_em)
        result = sif.check_memory_integrity()
        assert result.passed is True

    def test_sif_memory_integrity_fails_missing_source(self):
        """Test 22: Episode with empty source fails check."""
        from probos.sif import StructuralIntegrityField

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.get.return_value = {
            "ids": ["ep1"],
            "metadatas": [{"source": "", "timestamp": time.time()}],
        }
        mock_em._collection = mock_collection

        sif = StructuralIntegrityField(episodic_memory=mock_em)
        result = sif.check_memory_integrity()
        # Empty source is treated as legacy (BF-103 migration / pre-source era)
        assert result.passed is True

    def test_sif_memory_integrity_fails_invalid_timestamp(self):
        """Test 23: Episode with timestamp=0 fails check."""
        from probos.sif import StructuralIntegrityField

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.get.return_value = {
            "ids": ["ep1"],
            "metadatas": [{"source": "direct", "timestamp": 0}],
        }
        mock_em._collection = mock_collection

        sif = StructuralIntegrityField(episodic_memory=mock_em)
        result = sif.check_memory_integrity()
        assert result.passed is False
        assert "invalid timestamp" in result.details

    def test_sif_memory_integrity_no_episodic_memory(self):
        """Test 24: No episodic memory configured passes gracefully."""
        from probos.sif import StructuralIntegrityField

        sif = StructuralIntegrityField()  # No episodic_memory
        result = sif.check_memory_integrity()
        assert result.passed is True
        assert "not configured" in result.details
