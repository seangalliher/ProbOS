"""AD-514: Tests for public API methods on target objects."""

from __future__ import annotations

import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.llm_client import BaseLLMClient
from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# 1. AgentSpawner
# ---------------------------------------------------------------------------

class TestAgentSpawnerPublicAPI:
    def _make_spawner(self):
        from probos.substrate.spawner import AgentSpawner
        registry = MagicMock()
        spawner = AgentSpawner(registry)
        return spawner

    def test_get_template_missing(self):
        s = self._make_spawner()
        assert s.get_template("nonexistent") is None

    def test_get_template_present(self):
        s = self._make_spawner()
        s._templates["scout"] = object
        assert s.get_template("scout") is object

    def test_list_templates_copy(self):
        s = self._make_spawner()
        s._templates["a"] = int
        s._templates["b"] = str
        result = s.list_templates()
        assert result == {"a": int, "b": str}
        # Must be a copy
        result["c"] = float
        assert "c" not in s._templates

    def test_iter_templates(self):
        s = self._make_spawner()
        s._templates["x"] = list
        pairs = list(s.iter_templates())
        assert ("x", list) in pairs

    def test_list_templates_empty(self):
        s = self._make_spawner()
        s._templates = {}
        assert s.list_templates() == {}

    def test_iter_templates_empty(self):
        s = self._make_spawner()
        s._templates = {}
        assert list(s.iter_templates()) == []

    def test_replace_template(self):
        s = self._make_spawner()
        s._templates["scout"] = int
        s.replace_template("scout", str)
        assert s._templates["scout"] is str

    def test_replace_template_unknown(self):
        s = self._make_spawner()
        with pytest.raises(KeyError):
            s.replace_template("no_such_type", int)


# ---------------------------------------------------------------------------
# 2. HebbianRouter
# ---------------------------------------------------------------------------

class TestHebbianRouterPublicAPI:
    def _make_router(self):
        from probos.mesh.routing import HebbianRouter
        return HebbianRouter()

    def test_get_all_weights_empty(self):
        r = self._make_router()
        assert r.get_all_weights() == {}

    def test_get_all_compat_weights_empty(self):
        r = self._make_router()
        assert r.get_all_compat_weights() == {}

    def test_get_all_weights_copy(self):
        r = self._make_router()
        r._weights[("a", "b", "intent")] = 0.5
        result = r.get_all_weights()
        assert result == {("a", "b", "intent"): 0.5}
        result[("x", "y", "z")] = 1.0
        assert ("x", "y", "z") not in r._weights

    def test_set_weight(self):
        r = self._make_router()
        r.set_weight(("a", "b", "intent"), 0.7)
        assert r._weights[("a", "b", "intent")] == 0.7

    def test_remove_weights_for_agent(self):
        r = self._make_router()
        r._weights[("a", "b", "intent")] = 0.5
        r._weights[("c", "d", "intent")] = 0.3
        r.remove_weights_for_agent("b")
        assert ("a", "b", "intent") not in r._weights
        assert ("c", "d", "intent") in r._weights

    def test_get_all_compat_weights(self):
        r = self._make_router()
        r._compat_weights[("a", "b")] = 0.6
        assert r.get_all_compat_weights() == {("a", "b"): 0.6}

    def test_set_compat_weight(self):
        r = self._make_router()
        r.set_compat_weight(("x", "y"), 0.9)
        assert r._compat_weights[("x", "y")] == 0.9

    def test_remove_weights_for_absent_agent(self):
        r = self._make_router()
        r._weights[("a", "b", "intent")] = 1.0
        r.remove_weights_for_agent("z")  # not in any key
        assert len(r.get_all_weights()) == 1

    def test_remove_compat_weights_for_agent(self):
        r = self._make_router()
        r._compat_weights[("a", "b")] = 0.5
        r._compat_weights[("c", "d")] = 0.3
        r.remove_compat_weights_for_agent("a")
        assert ("a", "b") not in r._compat_weights
        assert ("c", "d") in r._compat_weights


# ---------------------------------------------------------------------------
# 3. WardRoomService
# ---------------------------------------------------------------------------

class TestWardRoomPublicAPI:
    def test_set_ontology(self):
        from probos.ward_room import WardRoomService
        ws = WardRoomService()
        mock_onto = MagicMock()
        ws.set_ontology(mock_onto)
        assert ws._ontology is mock_onto

    def test_is_started_false(self):
        from probos.ward_room import WardRoomService
        ws = WardRoomService()
        assert ws.is_started is False

    def test_is_started_true(self):
        from probos.ward_room import WardRoomService
        ws = WardRoomService()
        ws._db = MagicMock()  # simulate active connection
        assert ws.is_started is True

    @pytest.mark.asyncio
    async def test_post_system_message_no_db(self):
        from probos.ward_room import WardRoomService
        ws = WardRoomService()
        # Should not raise
        await ws.post_system_message("bridge", "Test message")


# ---------------------------------------------------------------------------
# 4. ResourcePool
# ---------------------------------------------------------------------------

class TestResourcePoolPublicAPI:
    def _make_pool(self):
        from probos.substrate.pool import ResourcePool
        from probos.config import PoolConfig
        spawner = MagicMock()
        registry = MagicMock()
        config = PoolConfig()
        pool = ResourcePool("test", "scout", spawner, registry, config)
        return pool

    def test_get_agent_ids_empty(self):
        pool = self._make_pool()
        assert pool.get_agent_ids() == []

    def test_get_agent_ids_copy(self):
        pool = self._make_pool()
        pool._agent_ids = ["a", "b"]
        result = pool.get_agent_ids()
        assert result == ["a", "b"]
        result.append("c")
        assert len(pool._agent_ids) == 2

    def test_contains_agent_present(self):
        pool = self._make_pool()
        pool._agent_ids = ["agent_1"]
        assert pool.contains_agent("agent_1") is True

    def test_contains_agent_absent(self):
        pool = self._make_pool()
        pool._agent_ids = ["agent_1"]
        assert pool.contains_agent("agent_2") is False

    def test_remove_agent_by_id(self):
        pool = self._make_pool()
        pool._agent_ids = ["a", "b", "c"]
        pool.remove_agent_by_id("b")
        assert "b" not in pool._agent_ids

    def test_remove_agent_by_id_missing(self):
        pool = self._make_pool()
        pool._agent_ids = ["agent_1"]
        pool.remove_agent_by_id("agent_99")  # should not raise
        assert pool.get_agent_ids() == ["agent_1"]


# ---------------------------------------------------------------------------
# 5. TrustNetwork
# ---------------------------------------------------------------------------

class TestTrustNetworkPublicAPI:
    def test_remove_agent(self):
        from probos.consensus.trust import TrustNetwork, TrustRecord
        tn = TrustNetwork()
        tn._records["agent_1"] = TrustRecord(agent_id="agent_1")
        tn.remove_agent("agent_1")
        assert "agent_1" not in tn._records

    def test_remove_agent_missing(self):
        from probos.consensus.trust import TrustNetwork
        tn = TrustNetwork()
        # Should not raise
        tn.remove_agent("nonexistent")


# ---------------------------------------------------------------------------
# 6. DreamScheduler
# ---------------------------------------------------------------------------

class TestDreamSchedulerPublicAPI:
    def test_set_callbacks(self):
        from probos.cognitive.dreaming import DreamScheduler, DreamingEngine
        engine = MagicMock(spec=DreamingEngine)
        ds = DreamScheduler(engine)
        pre = lambda: None
        post = lambda r: None
        micro = lambda r: None
        ds.set_callbacks(pre_dream=pre, post_dream=post, post_micro_dream=micro)
        assert ds._pre_dream_fn is pre
        assert ds._post_dream_fn is post
        assert ds._post_micro_dream_fn is micro

    def test_set_callbacks_partial(self):
        from probos.cognitive.dreaming import DreamScheduler, DreamingEngine
        engine = MagicMock(spec=DreamingEngine)
        ds = DreamScheduler(engine)
        original_post = ds._post_dream_fn
        fn = lambda: None
        ds.set_callbacks(pre_dream=fn)
        assert ds._pre_dream_fn is fn
        assert ds._post_dream_fn is original_post


# ---------------------------------------------------------------------------
# 7. ProactiveCognitiveLoop
# ---------------------------------------------------------------------------

class TestProactiveLoopPublicAPI:
    def test_set_knowledge_store(self):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop()
        store = MagicMock()
        loop.set_knowledge_store(store)
        assert loop._knowledge_store is store

    def test_get_cooldowns_copy(self):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop()
        loop._agent_cooldowns = {"agent_1": 300.0}
        result = loop.get_cooldowns()
        assert result == {"agent_1": 300.0}
        result["agent_2"] = 600.0
        assert "agent_2" not in loop._agent_cooldowns

    def test_get_cooldowns_empty(self):
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop()
        assert loop.get_cooldowns() == {}


# ---------------------------------------------------------------------------
# 8. SelfModificationPipeline
# ---------------------------------------------------------------------------

class TestSelfModPipelinePublicAPI:
    def _make_pipeline(self):
        from probos.cognitive.self_mod import SelfModificationPipeline
        return SelfModificationPipeline(
            designer=MagicMock(),
            validator=MagicMock(),
            sandbox=MagicMock(),
            monitor=MagicMock(),
            config=MagicMock(),
            register_fn=AsyncMock(),
            create_pool_fn=AsyncMock(),
            set_trust_fn=MagicMock(),
        )

    def test_validator_property(self):
        p = self._make_pipeline()
        assert p.validator is p._validator

    def test_sandbox_property(self):
        p = self._make_pipeline()
        assert p.sandbox is p._sandbox

    def test_design_records_empty(self):
        p = self._make_pipeline()
        assert p.design_records == []

    def test_design_records_is_copy(self):
        p = self._make_pipeline()
        p._records = [MagicMock()]
        result = p.design_records
        assert len(result) == 1
        result.append(MagicMock())
        assert len(p._records) == 1


# ---------------------------------------------------------------------------
# 9. IntentDecomposer
# ---------------------------------------------------------------------------

class TestIntentDecomposerPublicAPI:
    def _make_decomposer(self):
        from probos.cognitive.decomposer import IntentDecomposer
        from probos.cognitive.working_memory import WorkingMemoryManager
        llm = AsyncMock(spec=BaseLLMClient)
        wm = WorkingMemoryManager()
        return IntentDecomposer(llm, wm)

    def test_set_callsign_map(self):
        d = self._make_decomposer()
        d.set_callsign_map({"wesley": "scout"})
        assert d._callsign_map == {"wesley": "scout"}

    def test_intent_descriptor_count_empty(self):
        d = self._make_decomposer()
        assert d.intent_descriptor_count == 0

    def test_intent_descriptor_count(self):
        from probos.types import IntentDescriptor
        d = self._make_decomposer()
        d._intent_descriptors = [
            IntentDescriptor(name="a", params={}, description="test"),
            IntentDescriptor(name="b", params={}, description="test2"),
        ]
        assert d.intent_descriptor_count == 2


# ---------------------------------------------------------------------------
# 10. CapabilityRegistry
# ---------------------------------------------------------------------------

class TestCapabilityRegistryPublicAPI:
    def test_get_all_capabilities_empty(self):
        from probos.mesh.capability import CapabilityRegistry
        cr = CapabilityRegistry()
        assert cr.get_all_capabilities() == {}

    def test_get_all_capabilities_copy(self):
        from probos.mesh.capability import CapabilityRegistry
        cr = CapabilityRegistry()
        cr._capabilities["agent_1"] = [MagicMock()]
        result = cr.get_all_capabilities()
        assert "agent_1" in result
        result["agent_2"] = []
        assert "agent_2" not in cr._capabilities


# ---------------------------------------------------------------------------
# 11. EscalationManager
# ---------------------------------------------------------------------------

class TestEscalationManagerPublicAPI:
    def test_set_surge_callback(self):
        from probos.consensus.escalation import EscalationManager
        em = EscalationManager(runtime=MagicMock(spec=ProbOSRuntime), llm_client=AsyncMock(spec=BaseLLMClient))
        fn = AsyncMock()
        em.set_surge_callback(fn)
        assert em._surge_fn is fn


# ---------------------------------------------------------------------------
# 12. IntentBus
# ---------------------------------------------------------------------------

class TestIntentBusPublicAPI:
    def test_set_federation_handler(self):
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        bus = IntentBus(SignalManager())
        fn = AsyncMock()
        bus.set_federation_handler(fn)
        assert bus._federation_fn is fn


# ---------------------------------------------------------------------------
# 13. WorkflowCache
# ---------------------------------------------------------------------------

class TestWorkflowCachePublicAPI:
    def test_restore_entry(self):
        from probos.cognitive.workflow_cache import WorkflowCache
        cache = WorkflowCache()
        entry = MagicMock()
        cache.restore_entry("test_key", entry)
        assert cache._cache["test_key"] is entry

    def test_restore_entry_overwrites(self):
        from probos.cognitive.workflow_cache import WorkflowCache
        cache = WorkflowCache()
        cache._cache["key"] = MagicMock()
        new_val = MagicMock()
        cache.restore_entry("key", new_val)
        assert cache._cache["key"] is new_val


# ---------------------------------------------------------------------------
# 14. PoolGroupRegistry
# ---------------------------------------------------------------------------

class TestPoolGroupRegistryPublicAPI:
    def test_get_group_for_pool_missing(self):
        from probos.substrate.pool_group import PoolGroupRegistry
        pgr = PoolGroupRegistry()
        assert pgr.get_group_for_pool("nonexistent") is None

    def test_get_group_for_pool_present(self):
        from probos.substrate.pool_group import PoolGroupRegistry, PoolGroup
        pgr = PoolGroupRegistry()
        pgr.register(PoolGroup(name="bridge", display_name="Bridge", pool_names={"captain"}))
        assert pgr.get_group_for_pool("captain") == "bridge"


# ---------------------------------------------------------------------------
# 15. CallsignRegistry
# ---------------------------------------------------------------------------

class TestCallsignRegistryPublicAPI:
    def test_get_profile_missing(self):
        from probos.crew_profile import CallsignRegistry
        cr = CallsignRegistry()
        assert cr.get_profile("nonexistent") is None

    def test_get_profile_present(self):
        from probos.crew_profile import CallsignRegistry
        cr = CallsignRegistry()
        cr._type_to_profile["scout"] = {"display_name": "Wesley", "department": "Science"}
        result = cr.get_profile("scout")
        assert result == {"display_name": "Wesley", "department": "Science"}


# ---------------------------------------------------------------------------
# 16. BaseAgent
# ---------------------------------------------------------------------------

class TestBaseAgentPublicAPI:
    def _make_agent(self):
        from probos.substrate.agent import BaseAgent

        class TestAgent(BaseAgent):
            agent_type = "test"
            async def perceive(self, intent): pass
            async def decide(self, obs): pass
            async def act(self, plan): pass
            async def report(self, result): return {}

        return TestAgent()

    def test_set_temporal_context(self):
        agent = self._make_agent()
        agent.set_temporal_context(1000.0, 2000.0)
        assert agent._birth_timestamp == 1000.0
        assert agent._system_start_time == 2000.0

    def test_has_llm_client_false(self):
        agent = self._make_agent()
        assert agent.has_llm_client is False

    def test_has_llm_client_true(self):
        agent = self._make_agent()
        agent._llm_client = AsyncMock(spec=BaseLLMClient)
        assert agent.has_llm_client is True

    def test_llm_client_none(self):
        agent = self._make_agent()
        assert agent.llm_client is None

    def test_llm_client_present(self):
        agent = self._make_agent()
        mock_client = AsyncMock(spec=BaseLLMClient)
        agent._llm_client = mock_client
        assert agent.llm_client is mock_client

    def test_replace_id(self):
        agent = self._make_agent()
        old_id = agent.id
        agent._replace_id("new_id_123")
        assert agent.id == "new_id_123"


# ---------------------------------------------------------------------------
# 17. VitalsMonitorAgent
# ---------------------------------------------------------------------------

class TestVitalsMonitorPublicAPI:
    def _make_monitor(self):
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
        return VitalsMonitorAgent(pool="medical", runtime=MagicMock(spec=ProbOSRuntime))

    def test_latest_vitals_empty(self):
        vm = self._make_monitor()
        assert vm.latest_vitals is None

    def test_latest_vitals_present(self):
        vm = self._make_monitor()
        vm._window.append({"pulse": 1})
        vm._window.append({"pulse": 2})
        assert vm.latest_vitals == {"pulse": 2}

    def test_vitals_window_copy(self):
        vm = self._make_monitor()
        vm._window.append({"pulse": 1})
        result = vm.vitals_window
        assert result == [{"pulse": 1}]
        result.append({"pulse": 2})
        assert len(vm._window) == 1
