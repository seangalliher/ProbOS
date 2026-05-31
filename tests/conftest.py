"""Shared test fixtures."""

import os
import pytest

from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.config import PoolConfig

# AD-721i: defense-in-depth pytest collection ignore for the bundled in-Blender
# render script. ``pyproject.toml`` already pins ``testpaths = ["tests"]`` so
# nothing under ``src/`` is collected — this glob is belt-and-suspenders so a
# future test layout change can't accidentally collect ``render_avatar.py``,
# which imports ``bpy`` (only available inside Blender's subprocess Python).
collect_ignore_glob = ["**/_blender/**"]

# BF-245: Disable real NATS in tests at import time, before any fixtures run.
# Module-level (not autouse fixture) so session/module-scoped fixtures that
# construct SystemConfig see the override. setdefault allows opt-in:
#   PROBOS_NATS_ENABLED=true pytest tests/test_nats_integration.py
os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")


@pytest.fixture(scope="session", autouse=True)
def _ad682_isolated_data_dir(tmp_path_factory, worker_id):
    """AD-682: Per-xdist-worker isolated data dir.

    Each xdist worker (or master in serial mode) gets its own tmp directory
    used as PROBOS_DATA_DIR. Subsystems that resolve paths from data_dir
    (ChromaDB, ship-records, scout_seen.json, session state) land in
    worker-private space. Eliminates SQLite lock contention and filesystem
    races at high parallelism (-n auto).

    The override is set via os.environ so it is visible to subprocess and
    to subsystems that read env directly (parity with BF-245 PROBOS_NATS_ENABLED).
    """
    suffix = worker_id if worker_id != "master" else "master"
    data_dir = tmp_path_factory.mktemp(f"probos_data_{suffix}", numbered=False)
    prior = os.environ.get("PROBOS_DATA_DIR")
    os.environ["PROBOS_DATA_DIR"] = str(data_dir)
    try:
        yield data_dir
    finally:
        if prior is None:
            os.environ.pop("PROBOS_DATA_DIR", None)
        else:
            os.environ["PROBOS_DATA_DIR"] = prior


@pytest.fixture(scope="session", autouse=True)
def _ad682_chroma_path_sanity(_ad682_isolated_data_dir, worker_id):
    """AD-682: Warn if ChromaDB lands outside the worker's isolated data dir.

    Diagnostic only — does NOT raise. Multiple xdist workers share the
    project's `data/` directory on disk (it's not under the per-worker tmp),
    so any cross-worker mtime change would race-trigger a hard assertion.
    Instead this fixture prints a warning if rogue writes happen, which
    surfaces the regression without breaking parallel runs.
    """
    import glob

    before = {
        p: os.stat(p).st_mtime_ns
        for p in glob.glob("data/**/chroma.sqlite3*", recursive=True)
    }
    yield
    # Only the master worker performs the post-check to avoid xdist races.
    if worker_id != "master":
        return
    isolated = str(_ad682_isolated_data_dir)
    rogue = [
        p for p in glob.glob("data/**/chroma.sqlite3*", recursive=True)
        if not p.startswith(isolated) and before.get(p) != os.stat(p).st_mtime_ns
    ]
    if rogue:
        import warnings
        warnings.warn(
            f"AD-682: ChromaDB wrote outside isolated data dir: {rogue}. "
            f"A subsystem may be bypassing PROBOS_DATA_DIR resolution.",
            RuntimeWarning,
            stacklevel=2,
        )


@pytest.fixture(autouse=True)
def _ad682_clear_module_caches():
    """AD-682: Reset module-level caches that mutate during tests.

    Without this, test execution order affects results when the standing
    orders cache or personality block cache picks up state from a prior test.
    Add new caches here as they are discovered.
    """
    from probos.cognitive import standing_orders

    if hasattr(standing_orders, "clear_cache"):
        standing_orders.clear_cache()
    if hasattr(standing_orders, "_build_personality_block"):
        try:
            standing_orders._build_personality_block.cache_clear()
        except AttributeError:
            pass
    yield


@pytest.fixture(autouse=True)
def _bf326_no_magicmock_pollution(request):
    """BF-326: Auto-clean any ``MagicMock/`` directory a test leaves in the repo root.

    Root cause this guards against: a test passes a bare ``MagicMock()`` (or a
    ``MagicMock(spec=ProbOSRuntime)``) where a real filesystem path is expected.
    Many production code paths (``api.create_app`` static mounts,
    ``startup.finalize`` data-dir creation, ``DesktopLifecycle`` lock-file dir)
    then call ``Path(mock).mkdir(...)``, which stringifies the mock to
    ``"MagicMock/mock.<attr>"`` and creates stray directories under the project
    root that get accidentally committed.

    Because the pollution has many independent path vectors across ~18 API test
    modules, a per-test neutralization is brittle whack-a-mole. This janitor is
    the robust, vector-agnostic fix: it removes any ``MagicMock/`` dir a test
    creates and emits a warning (so offenders stay discoverable) without failing
    the test. Combined with the ``MagicMock/`` ``.gitignore`` rule, stray dirs can
    never reach the repository.

    Function-scoped so the warning pins the exact offending test.
    """
    repo_root = Path(__file__).resolve().parent.parent
    mm_dir = repo_root / "MagicMock"
    existed_before = mm_dir.exists()
    try:
        yield
    finally:
        if mm_dir.exists() and not existed_before:
            import shutil
            import warnings

            shutil.rmtree(mm_dir, ignore_errors=True)
            warnings.warn(
                f"BF-326: test '{request.node.nodeid}' created a 'MagicMock/' "
                "directory in the repo root (auto-cleaned). A MagicMock was "
                "passed where a real filesystem path is expected; production "
                "mkdir() then created stray dirs. Prefer a real tmp_path / real "
                "config for path-typed arguments.",
                stacklevel=2,
            )


def pytest_sessionfinish(session, exitstatus):
    """BF-326: final sweep of any ``MagicMock/`` directory left at session end.

    The function-scoped ``_bf326_no_magicmock_pollution`` janitor cleans dirs a
    test creates during its own scope, but module/session-scoped fixture
    teardowns (e.g. a module-scoped ``TestClient`` whose app-shutdown path calls
    ``mkdir``) can create the dir *after* the last function teardown. This hook
    guarantees the repo root is clean once the session ends.
    """
    import shutil

    repo_root = Path(__file__).resolve().parent.parent
    mm_dir = repo_root / "MagicMock"
    if mm_dir.exists():
        shutil.rmtree(mm_dir, ignore_errors=True)


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
def real_nats(monkeypatch):
    """Opt-in fixture: re-enable real NATS for a specific test.

    Usage: add `real_nats` to a test's parameter list. The test will
    use the real NATSBus instead of being blocked by BF-245's global
    PROBOS_NATS_ENABLED=false default.
    """
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")


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
    from probos.notifications import NotificationQueue
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.mesh.gossip import GossipProtocol
    from probos.substrate.pool_group import PoolGroupRegistry

    rt = MagicMock(spec=ProbOSRuntime)

    # Pre-configure common service sub-mocks with their own specs
    rt.registry = MagicMock(spec=AgentRegistry)
    rt.registry.all.return_value = []
    rt.registry.get.return_value = None

    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.trust_network.get_score.return_value = 0.5
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

    # AD-722b-1a (Wave 162): real SystemConfig() — defaults already match the
    # legacy MagicMock attribute assertions (onboarding.enabled=True,
    # naming_ceremony=True). Removes the routers/auth.py:43 isinstance guard
    # that previously absorbed MagicMock-shaped config objects.
    rt.config = SystemConfig()

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
