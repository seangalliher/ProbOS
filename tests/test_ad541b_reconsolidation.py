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
import asyncio
import ast
import hashlib
import inspect
import json
import logging
import re
import time
import textwrap
from types import SimpleNamespace
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
from probos.types import (
    AnchorFrame,
    Episode,
    EpisodeDuplicatePolicy,
    EpisodeStoreOutcome,
    MemorySource,
)


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


def _make_ad599_episode(**overrides) -> Episode:
    content = overrides.pop("user_input", "[Reflection] serialized primary authority")
    defaults = {
        "id": f"reflection-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}",
        "timestamp": 100.0,
        "user_input": content,
        "dag_summary": {
            "type": "reflection",
            "source": "dream_consolidation",
            "involved_agents": ["yeo"],
        },
        "outcomes": [],
        "reflection": content,
        "agent_ids": ["yeo"],
        "duration_ms": 0.0,
        "shapley_values": {},
        "trust_deltas": [],
        "source": MemorySource.REFLECTION,
        "anchors": AnchorFrame(trigger_type="dream_consolidation"),
        "importance": 8,
    }
    defaults.update(overrides)
    return Episode(**defaults)


def _store_start_barrier(expected: int):
    started = 0
    all_started = asyncio.Event()

    async def _run(store_call):
        nonlocal started
        started += 1
        if started == expected:
            all_started.set()
        return await store_call

    return _run, all_started


class _FirstWinsCollection:
    """Synchronous Chroma-shaped first-wins collection for lock tests."""

    def __init__(self, *, fail_add_once: bool = False) -> None:
        self.rows: dict[str, tuple[str, dict]] = {}
        self.add_calls = 0
        self.fail_add_once = fail_add_once

    def get(self, *, ids=None, include=None, **_kwargs):
        if ids:
            found = [episode_id for episode_id in ids if episode_id in self.rows]
            result = {"ids": found}
            if include and "metadatas" in include:
                result["metadatas"] = [self.rows[episode_id][1] for episode_id in found]
            if include and "documents" in include:
                result["documents"] = [self.rows[episode_id][0] for episode_id in found]
            return result
        return {"ids": [], "metadatas": [], "documents": []}

    def add(self, *, ids, documents, metadatas):
        self.add_calls += 1
        if self.fail_add_once:
            self.fail_add_once = False
            raise RuntimeError("injected primary add failure")
        for episode_id, document, metadata in zip(ids, documents, metadatas):
            self.rows.setdefault(episode_id, (document, metadata))

    def count(self):
        return len(self.rows)


class _BlockingFts:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.execute_calls = 0
        self.commit_calls = 0

    async def execute(self, *_args):
        self.execute_calls += 1
        self.entered.set()
        await self.release.wait()

    async def commit(self):
        self.commit_calls += 1


class _RecordingParticipantIndex:
    def __init__(self) -> None:
        self.calls = 0

    async def record_episode(self, *_args) -> None:
        self.calls += 1


class _RecordingEvolver:
    def __init__(self) -> None:
        self.calls = 0

    async def evolve_on_store(self, _episode) -> None:
        self.calls += 1


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
        outcome = await em.store(ep)
        assert outcome is EpisodeStoreOutcome.STORED
        mock_collection.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_duplicate_episode_id_skipped(self):
        """Test 17: Duplicate episode ID is skipped (not overwritten)."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        ep = _make_episode()
        metadata = EpisodicMemory._episode_to_metadata(ep)
        mock_collection.get.return_value = {
            "ids": [ep.id],
            "metadatas": [metadata],
            "documents": [ep.user_input],
        }
        em._collection = mock_collection

        outcome = await em.store(ep)

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        mock_collection.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_duplicate_logs_warning(self):
        """Test 18: Duplicate store logs a warning with 'write-once'."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        mock_collection = MagicMock()
        ep = _make_episode()
        metadata = EpisodicMemory._episode_to_metadata(ep)
        mock_collection.get.return_value = {
            "ids": [ep.id],
            "metadatas": [metadata],
            "documents": [ep.user_input],
        }
        em._collection = mock_collection

        with patch("probos.cognitive.episodic.logger") as mock_logger:
            outcome = await em.store(ep)

            assert outcome is EpisodeStoreOutcome.DUPLICATE
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

    @pytest.mark.asyncio
    async def test_conflicting_duplicate_warning_has_full_id_and_hash_context(
        self, caplog
    ):
        """BF-669: unexpected collisions retain full forensic context."""
        from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash

        existing = _make_episode(
            id="same-id-with-distinct-suffix", user_input="authoritative first"
        )
        incoming = dataclasses.replace(existing, user_input="conflicting second")
        metadata = EpisodicMemory._episode_to_metadata(existing)
        collection = MagicMock()

        def _get(*, ids=None, **_kwargs):
            if ids:
                return {
                    "ids": [existing.id],
                    "metadatas": [metadata],
                    "documents": [existing.user_input],
                }
            return {"ids": [], "metadatas": [], "documents": []}

        collection.get.side_effect = _get
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            await em.store(incoming)

        warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert existing.id in warnings[0]
        assert "policy=unexpected" in warnings[0]
        assert "reason=unexpected_duplicate" in warnings[0]
        incoming_prefix = compute_episode_hash(incoming)[:12]
        existing_prefix = compute_episode_hash(existing)[:12]
        assert len(incoming_prefix) == len(existing_prefix) == 12
        hash_match = re.search(
            r"incoming_hash=([0-9a-f]{12}) existing_hash=([0-9a-f]{12});",
            warnings[0],
        )
        assert hash_match is not None
        assert hash_match.groups() == (incoming_prefix, existing_prefix)
        assert "existing write remains authoritative" in warnings[0]
        assert existing.user_input not in warnings[0]
        assert incoming.user_input not in warnings[0]

    @pytest.mark.asyncio
    async def test_concurrent_same_id_calls_return_stored_and_duplicate(self, caplog):
        """BF-669: same-instance concurrent calls expose truthful outcomes."""
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        first = _make_ad599_episode()
        replay = dataclasses.replace(first, timestamp=first.timestamp + 1.0)
        lock = em._get_store_write_lock()
        await lock.acquire()
        run_store, all_started = _store_start_barrier(2)
        first_task = asyncio.create_task(
            run_store(em.store(
                first,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ))
        )
        replay_task = asyncio.create_task(
            run_store(em.store(
                replay,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ))
        )
        await all_started.wait()
        assert not first_task.done()
        assert not replay_task.done()
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.episodic"):
            lock.release()
            outcomes = await asyncio.gather(first_task, replay_task)

        assert sorted(outcome.value for outcome in outcomes) == [
            "duplicate",
            "stored",
        ]
        assert collection.add_calls == 1
        assert list(collection.rows) == [first.id]
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]

    def test_store_primary_lock_window_contains_no_await(self):
        """BF-669: the serialized primary authority window is synchronous."""
        from probos.cognitive.episodic import EpisodicMemory

        tree = ast.parse(textwrap.dedent(inspect.getsource(EpisodicMemory.store)))
        async_with = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncWith))

        assert not any(
            isinstance(node, ast.Await)
            for statement in async_with.body
            for node in ast.walk(statement)
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_policy", ["unexpected", True, object()])
    async def test_store_invalid_policy_rejected_before_any_mutation(
        self, invalid_policy
    ):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        collection = MagicMock()
        gate = MagicMock()
        tcm = MagicMock()
        em._collection = collection
        em._storage_gate = gate
        em._tcm = tcm

        with pytest.raises(TypeError, match="EpisodeDuplicatePolicy"):
            await em.store(
                _make_episode(), duplicate_policy=invalid_policy  # type: ignore[arg-type]
            )

        collection.get.assert_not_called()
        collection.add.assert_not_called()
        gate.evaluate.assert_not_called()
        tcm.update.assert_not_called()

    def test_store_lock_accessor_rejects_malformed_existing_attribute(self):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory.__new__(EpisodicMemory)
        em._store_write_lock = object()

        with pytest.raises(TypeError, match="asyncio.Lock"):
            em._get_store_write_lock()

    @pytest.mark.asyncio
    async def test_store_no_collection_returns_skipped_with_debug(self, caplog):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        episode = _make_episode(id="no-collection")

        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.episodic"):
            outcome = await em.store(episode)

        assert outcome is EpisodeStoreOutcome.SKIPPED
        assert "primary collection is unavailable" in caplog.text
        assert episode.id in caplog.text

    @pytest.mark.asyncio
    async def test_security_rejection_returns_skipped_without_primary_write(self):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        collection = _FirstWinsCollection()
        security_gate = MagicMock()
        security_gate.evaluate_store.return_value = SimpleNamespace(
            matched_pattern="injected-pattern",
            action="REJECT",
            reason="prompt_injection",
        )
        em._collection = collection
        em._security_gate = security_gate

        outcome = await em.store(_make_episode(agent_ids=[]))

        assert outcome is EpisodeStoreOutcome.SKIPPED
        assert collection.add_calls == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("skip_kind", ["rate", "content"])
    async def test_generic_admission_rejection_returns_skipped(self, skip_kind):
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory("/tmp/test_em")
        collection = _FirstWinsCollection()
        em._collection = collection
        em._is_rate_limited = MagicMock(return_value=skip_kind == "rate")
        em._is_duplicate_content = MagicMock(return_value=skip_kind == "content")

        outcome = await em.store(_make_episode(agent_ids=[]))

        assert outcome is EpisodeStoreOutcome.SKIPPED
        assert collection.add_calls == 0

    @pytest.mark.asyncio
    async def test_expected_replay_debug_has_full_context_and_no_warning(
        self, caplog
    ):
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        first = _make_ad599_episode(timestamp=100.0)
        replay = dataclasses.replace(first, timestamp=200.0)
        await em.store(first)

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.episodic"):
            outcome = await em.store(
                replay,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
        assert first.id in caplog.text
        assert "policy=expect_same_reflection" in caplog.text
        assert "equivalence=timestamp_neutral" in caplog.text
        assert "incoming_hash=" in caplog.text
        assert "existing_hash=" in caplog.text
        assert "existing write remains authoritative" in caplog.text
        assert first.user_input not in caplog.text

    @pytest.mark.asyncio
    async def test_default_policy_exact_replay_remains_unexpected_warning(
        self, caplog
    ):
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        first = _make_ad599_episode(timestamp=100.0)
        await em.store(first)

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            outcome = await em.store(dataclasses.replace(first, timestamp=200.0))

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        assert "policy=unexpected" in caplog.text
        assert "reason=unexpected_duplicate" in caplog.text
        assert first.id in caplog.text

    @pytest.mark.asyncio
    async def test_malformed_stored_metadata_expected_policy_warns_conflict(
        self, caplog
    ):
        from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash

        incoming = _make_ad599_episode()
        collection = _FirstWinsCollection()
        malformed = EpisodicMemory._episode_to_metadata(incoming)
        malformed["dag_summary_json"] = "{bad json"
        collection.rows[incoming.id] = (incoming.user_input, malformed)
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            outcome = await em.store(
                incoming,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        assert "policy=expect_same_reflection" in caplog.text
        assert "reason=content_conflict" in caplog.text
        assert "existing write remains authoritative" in caplog.text
        incoming_prefix = compute_episode_hash(incoming)[:12]
        existing_prefix = malformed["content_hash"][:12]
        assert len(incoming_prefix) == len(existing_prefix) == 12
        hash_match = re.search(
            r"incoming_hash=([0-9a-f]{12}) existing_hash=([0-9a-f]{12});",
            caplog.text,
        )
        assert hash_match is not None
        assert hash_match.groups() == (incoming_prefix, existing_prefix)
        assert incoming.user_input not in caplog.text
        assert incoming.reflection not in caplog.text
        assert collection.add_calls == 0

    @pytest.mark.asyncio
    async def test_same_malformed_id_collision_warns_with_exact_hashes_and_first_authority(
        self, caplog
    ):
        """BF-669: a same-ID malformed reflection reaches proof validation."""
        from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash

        malformed_id = "reflection-0000000000000000"
        existing = _make_ad599_episode(id=malformed_id, timestamp=100.0)
        incoming = dataclasses.replace(existing, timestamp=200.0)
        collection = _FirstWinsCollection()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection

        assert await em.store(existing) is EpisodeStoreOutcome.STORED
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            outcome = await em.store(
                incoming,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        warnings = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        warning = warnings[0]
        incoming_prefix = compute_episode_hash(incoming)[:12]
        existing_prefix = compute_episode_hash(existing)[:12]
        assert len(incoming_prefix) == len(existing_prefix) == 12
        assert malformed_id in warning
        assert "policy=expect_same_reflection" in warning
        assert "reason=content_conflict" in warning
        hash_match = re.search(
            r"incoming_hash=([0-9a-f]{12}) existing_hash=([0-9a-f]{12});",
            warning,
        )
        assert hash_match is not None
        assert hash_match.groups() == (incoming_prefix, existing_prefix)
        assert "existing write remains authoritative" in warning
        assert existing.user_input not in warning
        assert existing.reflection not in warning
        assert collection.count() == 1
        stored_document, stored_metadata = collection.rows[malformed_id]
        stored = EpisodicMemory._metadata_to_episode(
            malformed_id,
            stored_document,
            stored_metadata,
        )
        assert stored.id == existing.id
        assert stored.timestamp == existing.timestamp
        assert stored.user_input == existing.user_input
        assert stored.reflection == existing.reflection

    @pytest.mark.asyncio
    async def test_existing_id_precedes_all_stateful_admission(self):
        from probos.cognitive.episodic import EpisodicMemory

        existing = _make_episode(id="authoritative-id", user_input="first")
        collection = _FirstWinsCollection()
        collection.rows[existing.id] = (
            EpisodicMemory._prepare_document(existing),
            EpisodicMemory._episode_to_metadata(existing),
        )
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        em._storage_gate = MagicMock()
        em._security_gate = MagicMock()
        em._is_rate_limited = MagicMock(return_value=True)
        em._is_duplicate_content = MagicMock(return_value=True)
        em._tcm = MagicMock()
        em._fts_db = MagicMock()
        em._participant_index = MagicMock()
        em._reconsolidation_scheduler = MagicMock()
        em._retroactive_evolver = MagicMock()

        outcome = await em.store(dataclasses.replace(existing, timestamp=200.0))

        assert outcome is EpisodeStoreOutcome.DUPLICATE
        em._storage_gate.evaluate.assert_not_called()
        em._security_gate.evaluate_store.assert_not_called()
        em._is_rate_limited.assert_not_called()
        em._is_duplicate_content.assert_not_called()
        em._tcm.update.assert_not_called()
        em._fts_db.execute.assert_not_called()
        em._participant_index.record_episode.assert_not_called()
        em._reconsolidation_scheduler.schedule_review.assert_not_called()
        em._retroactive_evolver.evolve_on_store.assert_not_called()
        assert collection.add_calls == 0

    @pytest.mark.asyncio
    async def test_primary_lock_released_before_secondary_and_side_effects_once(self):
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection()
        fts = _BlockingFts()
        participant = _RecordingParticipantIndex()
        evolver = _RecordingEvolver()
        tcm = MagicMock()
        tcm.update.return_value = [0.1, 0.2]
        gate = MagicMock()
        gate.evaluate.return_value = SimpleNamespace(action="ACCEPT")
        scheduler = MagicMock()
        evictions = {"count": 0}

        async def _record_evict() -> None:
            evictions["count"] += 1

        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        em._fts_db = fts
        em._participant_index = participant
        em._retroactive_evolver = evolver
        em._tcm = tcm
        em._storage_gate = gate
        em._reconsolidation_scheduler = scheduler
        em._evict = _record_evict
        episode = _make_ad599_episode()
        first_task = asyncio.create_task(
            em.store(
                episode,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )
        )
        await fts.entered.wait()

        assert em._get_store_write_lock().locked() is False
        duplicate = await asyncio.wait_for(
            em.store(
                dataclasses.replace(episode, timestamp=200.0),
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ),
            timeout=1.0,
        )
        assert duplicate is EpisodeStoreOutcome.DUPLICATE
        assert not first_task.done()
        assert collection.add_calls == 1
        assert tcm.update.call_count == 1
        assert gate.evaluate.call_count == 1
        assert participant.calls == 0
        assert evolver.calls == 0
        assert scheduler.schedule_review.call_count == 0
        assert evictions["count"] == 0

        fts.release.set()
        assert await first_task is EpisodeStoreOutcome.STORED
        assert fts.execute_calls == 1
        assert fts.commit_calls == 1
        assert participant.calls == 1
        assert evolver.calls == 1
        assert scheduler.schedule_review.call_count == 1
        assert evictions["count"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_conflict_preserves_first_and_warns_once(self, caplog):
        from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash

        collection = _FirstWinsCollection()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        first = _make_ad599_episode()
        conflict = dataclasses.replace(first, agent_ids=["different-agent"])
        lock = em._get_store_write_lock()
        await lock.acquire()
        run_store, all_started = _store_start_barrier(2)
        first_task = asyncio.create_task(
            run_store(em.store(
                first,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ))
        )
        conflict_task = asyncio.create_task(
            run_store(em.store(
                conflict,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            ))
        )
        await all_started.wait()

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            lock.release()
            outcomes = await asyncio.gather(first_task, conflict_task)

        assert sorted(outcome.value for outcome in outcomes) == ["duplicate", "stored"]
        assert collection.add_calls == 1
        stored = EpisodicMemory._metadata_to_episode(
            first.id, collection.rows[first.id][0], collection.rows[first.id][1]
        )
        assert stored.agent_ids == first.agent_ids
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        warning = warnings[0].message
        assert "reason=content_conflict" in warning
        incoming_prefix = compute_episode_hash(conflict)[:12]
        existing_prefix = compute_episode_hash(first)[:12]
        hash_match = re.search(
            r"incoming_hash=([0-9a-f]{12}) existing_hash=([0-9a-f]{12});",
            warning,
        )
        assert hash_match is not None
        assert hash_match.groups() == (incoming_prefix, existing_prefix)
        assert "existing write remains authoritative" in warning
        assert first.user_input not in warning
        assert first.reflection not in warning

    @pytest.mark.asyncio
    async def test_add_failure_releases_lock_and_later_call_stores(self):
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection(fail_add_once=True)
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        episode = _make_episode(id="retry-after-failure", agent_ids=[])

        with pytest.raises(RuntimeError, match="primary add failure"):
            await em.store(episode)

        assert em._get_store_write_lock().locked() is False
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
        assert collection.add_calls == 2
        assert list(collection.rows) == [episode.id]

    @pytest.mark.asyncio
    async def test_primary_read_failure_and_cancellation_propagate_and_unlock(self):
        from probos.cognitive.episodic import EpisodicMemory

        for failure in (
            RuntimeError("injected primary read failure"),
            asyncio.CancelledError(),
        ):
            em = EpisodicMemory("/tmp/test_em")
            collection = MagicMock()
            collection.get.side_effect = failure
            em._collection = collection

            with pytest.raises(type(failure)):
                await em.store(_make_episode())

            assert em._get_store_write_lock().locked() is False
            collection.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancellation_while_waiting_for_lock_propagates_without_write(self):
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        lock = em._get_store_write_lock()
        await lock.acquire()
        run_store, all_started = _store_start_barrier(1)
        task = asyncio.create_task(
            run_store(em.store(_make_episode(agent_ids=[])))
        )
        await all_started.wait()
        assert not task.done()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert lock.locked() is True
        assert collection.rows == {}
        lock.release()
        assert await em.store(_make_episode(id="after-cancel", agent_ids=[])) is EpisodeStoreOutcome.STORED

    @pytest.mark.asyncio
    async def test_secondary_cancellation_leaves_primary_authoritative(self):
        from probos.cognitive.episodic import EpisodicMemory

        collection = _FirstWinsCollection()
        fts = _BlockingFts()
        em = EpisodicMemory("/tmp/test_em")
        em._collection = collection
        em._fts_db = fts
        episode = _make_ad599_episode()
        task = asyncio.create_task(
            em.store(
                episode,
                duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
            )
        )
        await fts.entered.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert em._get_store_write_lock().locked() is False
        assert list(collection.rows) == [episode.id]
        replay = await em.store(
            dataclasses.replace(episode, timestamp=200.0),
            duplicate_policy=EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION,
        )
        assert replay is EpisodeStoreOutcome.DUPLICATE
        assert collection.add_calls == 1


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
