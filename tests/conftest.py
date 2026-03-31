"""Shared test fixtures."""

import pytest

from unittest.mock import MagicMock, AsyncMock

from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.config import PoolConfig


def pytest_collection_modifyitems(config, items):
    """Skip live_llm tests unless explicitly requested with -m live_llm."""
    marker_expr = config.getoption("-m", default="")
    if marker_expr and "live_llm" in marker_expr:
        return
    skip_live = pytest.mark.skip(reason="live_llm tests only run with: pytest -m live_llm")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def spawner(registry):
    return AgentSpawner(registry)


@pytest.fixture
def pool_config():
    return PoolConfig(
        default_pool_size=3,
        max_pool_size=7,
        min_pool_size=2,
        spawn_cooldown_ms=100,
        health_check_interval_seconds=1.0,
    )


@pytest.fixture
def mock_runtime():
    """Shared spec'd ProbOSRuntime mock (BF-079 Phase 2)."""
    from probos.runtime import ProbOSRuntime
    from probos.consensus.trust import TrustNetwork
    from probos.ward_room import WardRoomService
    from probos.ward_room_router import WardRoomRouter
    from probos.cognitive.episodic import EpisodicMemory
    from probos.crew_profile import CallsignRegistry
    from probos.mesh.intent import IntentBus
    from probos.mesh.signal import SignalManager
    from probos.mesh.routing import HebbianRouter
    from probos.substrate.event_log import EventLog
    from probos.config import SystemConfig
    from probos.task_tracker import NotificationQueue
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.mesh.gossip import GossipProtocol
    from probos.substrate.pool_group import PoolGroupRegistry

    rt = MagicMock(spec=ProbOSRuntime)

    # Pre-configure common service sub-mocks with their own specs
    rt.registry = MagicMock(spec=AgentRegistry)
    rt.registry.all.return_value = []
    rt.registry.get.return_value = None

    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.trust_network.get_trust.return_value = 0.5
    rt.trust_network.get_or_create.return_value = MagicMock(trust_score=0.5)

    rt.ward_room = AsyncMock(spec=WardRoomService)
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)

    rt.episodic_memory = AsyncMock(spec=EpisodicMemory)
    rt.episodic_memory.recall.return_value = []

    rt.callsign_registry = MagicMock(spec=CallsignRegistry)
    rt.callsign_registry.resolve.return_value = None
    rt.callsign_registry.all_callsigns.return_value = {}

    rt.intent_bus = MagicMock(spec=IntentBus)
    rt.signal_manager = MagicMock(spec=SignalManager)
    rt.hebbian_router = MagicMock(spec=HebbianRouter)
    rt.event_log = AsyncMock(spec=EventLog)

    rt.config = MagicMock(spec=SystemConfig)
    rt.config.onboarding = MagicMock()
    rt.config.onboarding.enabled = True
    rt.config.onboarding.naming_ceremony = True
    rt.config.proactive = MagicMock()
    rt.config.proactive.enabled = False

    rt.spawner = MagicMock(spec=AgentSpawner)
    rt.pools = {}
    rt.pool_groups = MagicMock(spec=PoolGroupRegistry)

    rt.notification_queue = MagicMock(spec=NotificationQueue)
    rt.llm_client = AsyncMock(spec=BaseLLMClient)

    # Gossip protocol
    rt.gossip = MagicMock(spec=GossipProtocol)

    # Deferred services (None by default, tests set as needed)
    rt.ontology = None
    rt.acm = None
    rt.bridge_alerts = None
    rt.dream_scheduler = None
    rt.proactive_loop = None
    rt.codebase_index = None
    rt.self_mod_pipeline = None
    rt.self_mod_manager = None
    rt.dream_adapter = None
    rt.onboarding = None
    rt.warm_boot = None
    rt.feedback_engine = None
    rt.sif = None
    rt.initiative = None
    rt.build_queue = None
    rt.build_dispatcher = None
    rt.task_tracker = None
    rt.service_profiles = None
    rt.directive_store = None
    rt.persistent_task_store = None
    rt.work_item_store = None
    rt.cognitive_journal = None
    rt.skill_registry = None
    rt.skill_service = None
    rt.identity_registry = None
    rt.conn_manager = None
    rt.watch_manager = None
    rt.federation_bridge = None
    rt.behavioral_monitor = None
    rt._records_store = None
    rt._knowledge_store = None
    rt._system_qa = None
    rt._semantic_layer = None
    rt._emergent_detector = None
    rt._correction_detector = None
    rt._agent_patcher = None

    # Execution state
    rt._pending_proposal = None
    rt._last_execution = None
    rt._last_execution_text = None
    rt._last_feedback_applied = False
    rt._previous_execution = None

    # Boot state
    rt._cold_start = True
    rt._started = False
    rt._fresh_boot = True
    rt._start_time = 0.0
    rt._recent_errors = []

    return rt
