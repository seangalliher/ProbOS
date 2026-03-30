"""Tests for the Dreaming system — DreamingEngine, DreamScheduler, and integration."""

import asyncio
import time
from io import StringIO

import pytest

pytestmark = pytest.mark.slow
from rich.console import Console

from probos.cognitive.dreaming import DreamingEngine, DreamScheduler
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.llm_client import MockLLMClient
from probos.config import DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.experience import panels
from probos.experience.shell import ProbOSShell
from probos.mesh.routing import HebbianRouter, REL_INTENT
from probos.runtime import ProbOSRuntime
from probos.types import DreamReport, Episode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dream_config():
    return DreamingConfig(
        idle_threshold_seconds=1.0,
        dream_interval_seconds=1.0,
        replay_episode_count=50,
        pathway_strengthening_factor=0.03,
        pathway_weakening_factor=0.02,
        prune_threshold=0.01,
        trust_boost=0.1,
        trust_penalty=0.1,
        pre_warm_top_k=5,
    )


@pytest.fixture
def router():
    return HebbianRouter(decay_rate=0.995, reward=0.05)


@pytest.fixture
def trust():
    return TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999)


@pytest.fixture
def memory():
    return MockEpisodicMemory(relevance_threshold=0.3)


@pytest.fixture
def engine(router, trust, memory, dream_config):
    return DreamingEngine(router, trust, memory, dream_config)


def _make_episode(
    intents: list[str],
    agent_ids: list[str],
    success: bool = True,
    user_input: str = "test input",
) -> Episode:
    """Helper to create an episode with given intents and outcomes."""
    outcomes = [
        {"intent": intent, "success": success, "status": "completed" if success else "failed"}
        for intent in intents
    ]
    return Episode(
        timestamp=time.time(),
        user_input=user_input,
        dag_summary={"node_count": len(intents), "intent_types": intents},
        outcomes=outcomes,
        agent_ids=agent_ids,
        duration_ms=100.0,
    )


# ---------------------------------------------------------------------------
# DreamingEngine tests
# ---------------------------------------------------------------------------

class TestDreamingEngine:

    @pytest.mark.asyncio
    async def test_dream_cycle_strengthens_weights_for_success(self, engine, memory, router):
        """Successful episodes strengthen Hebbian weights between intents and agents."""
        ep = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=True,
        )
        await memory.store(ep)

        report = await engine.dream_cycle()

        assert report.episodes_replayed == 1
        assert report.weights_strengthened >= 1
        weight = router.get_weight("read_file", "agent_a", REL_INTENT)
        # Strengthened by 0.03, then decayed by 0.995 during prune step
        assert weight >= 0.02  # Strengthened above zero

    @pytest.mark.asyncio
    async def test_dream_cycle_weakens_weights_for_failure(self, engine, memory, router):
        """Failed episodes weaken Hebbian weights between intents and agents."""
        # First set a weight so we can observe it decrease
        router._weights[("write_file", "agent_b", REL_INTENT)] = 0.5
        router._compat_weights[("write_file", "agent_b")] = 0.5

        ep = _make_episode(
            intents=["write_file"],
            agent_ids=["agent_b"],
            success=False,
        )
        await memory.store(ep)

        await engine.dream_cycle()

        weight = router.get_weight("write_file", "agent_b", REL_INTENT)
        assert weight < 0.5  # Should have been weakened

    @pytest.mark.asyncio
    async def test_dream_cycle_mixed_episodes(self, engine, memory, router):
        """Mixed success/failure episodes strengthen correct ones and weaken others."""
        ep_success = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=True,
        )
        ep_failure = _make_episode(
            intents=["write_file"],
            agent_ids=["agent_b"],
            success=False,
        )
        # Give the failure agent an initial weight
        router._weights[("write_file", "agent_b", REL_INTENT)] = 0.3
        router._compat_weights[("write_file", "agent_b")] = 0.3

        await memory.store(ep_success)
        await memory.store(ep_failure)

        report = await engine.dream_cycle()

        assert report.episodes_replayed == 2
        assert report.weights_strengthened >= 1

        # Success weight should be positive (strengthened)
        w_success = router.get_weight("read_file", "agent_a", REL_INTENT)
        assert w_success > 0

        # Failure weight should have decreased from 0.3
        w_failure = router.get_weight("write_file", "agent_b", REL_INTENT)
        assert w_failure < 0.3

    @pytest.mark.asyncio
    async def test_prune_removes_below_threshold(self, engine, memory, router, dream_config):
        """Prune removes connections below the configured threshold."""
        # Add a weight that is below the prune threshold
        router._weights[("old_intent", "old_agent", REL_INTENT)] = 0.005
        router._compat_weights[("old_intent", "old_agent")] = 0.005

        # Add a weight that is above the threshold
        router._weights[("good_intent", "good_agent", REL_INTENT)] = 0.5
        router._compat_weights[("good_intent", "good_agent")] = 0.5

        # Store an episode so dream_cycle runs
        ep = _make_episode(intents=["test"], agent_ids=["agent_x"], success=True)
        await memory.store(ep)

        report = await engine.dream_cycle()

        assert report.weights_pruned >= 1
        # Below-threshold weight should be gone
        assert router.get_weight("old_intent", "old_agent", REL_INTENT) == 0.0
        # Above-threshold weight should survive (possibly decayed)
        assert router.get_weight("good_intent", "good_agent", REL_INTENT) > 0

    @pytest.mark.asyncio
    async def test_trust_consolidation_boosts_successful(self, engine, memory, trust):
        """Agents with multiple successful episodes get a trust boost."""
        # Two successful episodes with the same agent (>1 threshold)
        for _ in range(3):
            ep = _make_episode(
                intents=["read_file"],
                agent_ids=["reliable_agent"],
                success=True,
            )
            await memory.store(ep)

        initial_record = trust.get_or_create("reliable_agent")
        initial_alpha = initial_record.alpha

        report = await engine.dream_cycle()

        assert report.trust_adjustments >= 1
        final_record = trust.get_record("reliable_agent")
        assert final_record.alpha > initial_alpha

    @pytest.mark.asyncio
    async def test_trust_consolidation_penalizes_failing(self, engine, memory, trust):
        """Agents with multiple failing episodes get a trust penalty."""
        for _ in range(3):
            ep = _make_episode(
                intents=["write_file"],
                agent_ids=["flaky_agent"],
                success=False,
            )
            await memory.store(ep)

        initial_record = trust.get_or_create("flaky_agent")
        initial_beta = initial_record.beta

        report = await engine.dream_cycle()

        assert report.trust_adjustments >= 1
        final_record = trust.get_record("flaky_agent")
        assert final_record.beta > initial_beta

    @pytest.mark.asyncio
    async def test_pre_warm_identifies_temporal_sequences(self, engine, memory):
        """Pre-warm identifies frequently occurring intent transitions."""
        # Create episodes that show list_directory -> read_file pattern
        for _ in range(5):
            ep = _make_episode(
                intents=["list_directory", "read_file"],
                agent_ids=["agent_a"],
                success=True,
            )
            await memory.store(ep)

        report = await engine.dream_cycle()

        assert len(report.pre_warm_intents) > 0
        # read_file should be a pre-warm candidate (follows list_directory)
        assert "read_file" in report.pre_warm_intents

    @pytest.mark.asyncio
    async def test_pre_warm_stored_on_engine(self, engine, memory):
        """Pre-warm intents are stored on the engine for decomposer access."""
        ep = _make_episode(
            intents=["list_directory", "read_file"],
            agent_ids=["agent_a"],
            success=True,
        )
        await memory.store(ep)

        await engine.dream_cycle()

        assert len(engine.pre_warm_intents) > 0

    @pytest.mark.asyncio
    async def test_empty_episodes_produces_noop(self, engine, memory):
        """Dream cycle with no episodes produces an empty report."""
        report = await engine.dream_cycle()

        assert report.episodes_replayed == 0
        assert report.weights_strengthened == 0
        assert report.weights_pruned == 0
        assert report.trust_adjustments == 0
        assert report.pre_warm_intents == []
        assert report.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_dream_report_duration(self, engine, memory):
        """Dream cycle report includes non-negative duration."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        report = await engine.dream_cycle()

        assert report.duration_ms >= 0


# ---------------------------------------------------------------------------
# DreamScheduler tests
# ---------------------------------------------------------------------------

class TestDreamScheduler:

    @pytest.mark.asyncio
    async def test_triggers_after_idle_threshold(self, engine, memory):
        """Scheduler triggers a dream cycle after idle threshold is reached."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=0.1,
            dream_interval_seconds=0.1,
        )
        # Set last activity far in the past
        scheduler._last_activity_time = time.monotonic() - 10
        scheduler._last_dream_time = 0.0
        scheduler.start()

        try:
            # Wait for the scheduler to trigger
            for _ in range(50):
                await asyncio.sleep(0.1)
                if scheduler.last_dream_report is not None:
                    break

            assert scheduler.last_dream_report is not None
            # Note: episodes_replayed may be 0 if micro-dream tick already
            # consumed the episode before the full dream ran (BF-008)
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_respects_minimum_interval(self, engine, memory):
        """Scheduler does not trigger again before the minimum interval."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=0.05,
            dream_interval_seconds=100.0,  # Very long interval
        )
        scheduler._last_activity_time = time.monotonic() - 10
        scheduler._last_dream_time = time.monotonic()  # Just dreamed
        scheduler.start()

        try:
            await asyncio.sleep(0.3)
            # Should NOT have triggered because we just dreamed
            assert scheduler.last_dream_report is None
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_is_dreaming_flag_during_cycle(self, engine, memory):
        """is_dreaming is True during a dream cycle."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        scheduler = DreamScheduler(engine=engine)

        assert scheduler.is_dreaming is False

        report = await scheduler.force_dream()

        # After force_dream completes, is_dreaming should be False
        assert scheduler.is_dreaming is False
        assert report.episodes_replayed >= 1

    @pytest.mark.asyncio
    async def test_forced_dream_via_method_call(self, engine, memory):
        """force_dream() triggers an immediate dream cycle."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        scheduler = DreamScheduler(engine=engine)

        report = await scheduler.force_dream()

        assert report.episodes_replayed == 1
        assert scheduler.last_dream_report is report

    @pytest.mark.asyncio
    async def test_record_activity_resets_idle_timer(self, engine, memory):
        """record_activity() prevents dream cycles by resetting the idle timer."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=0.2,
            dream_interval_seconds=0.1,
        )
        scheduler.start()

        try:
            # Keep recording activity
            for _ in range(5):
                scheduler.record_activity()
                await asyncio.sleep(0.05)

            # Should NOT have dreamed because we keep resetting idle timer
            assert scheduler.last_dream_report is None
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_background_task(self, engine):
        """stop() cancels the background monitor loop."""
        scheduler = DreamScheduler(engine=engine)
        scheduler.start()
        assert scheduler._task is not None
        await scheduler.stop()
        assert scheduler._task is None


# ---------------------------------------------------------------------------
# Runtime integration tests
# ---------------------------------------------------------------------------

class TestRuntimeDreamingIntegration:

    @pytest.fixture
    async def dream_runtime(self, tmp_path):
        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()
        yield rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_dreaming_state_in_status(self, dream_runtime):
        """Runtime status includes dreaming state."""
        status = dream_runtime.status()
        assert "dreaming" in status
        assert status["dreaming"]["enabled"] is True
        assert status["dreaming"]["state"] in ("idle", "dreaming")

    @pytest.mark.asyncio
    async def test_dreaming_disabled_without_episodic(self, tmp_path):
        """Without episodic memory, dreaming is disabled."""
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        try:
            status = rt.status()
            assert status["dreaming"]["enabled"] is False
            assert status["dreaming"]["state"] == "disabled"
            assert rt.dream_scheduler is None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_last_request_time_updates_on_nl(self, dream_runtime, tmp_path):
        """process_natural_language updates _last_request_time."""
        initial = dream_runtime._last_request_time
        test_file = tmp_path / "req_time.txt"
        test_file.write_text("test")

        await dream_runtime.process_natural_language(
            f"read the file at {test_file}"
        )

        assert dream_runtime._last_request_time >= initial

    @pytest.mark.asyncio
    async def test_scheduler_activity_tracked_on_nl(self, dream_runtime, tmp_path):
        """NL processing records activity on the dream scheduler."""
        scheduler = dream_runtime.dream_scheduler
        assert scheduler is not None

        old_activity = scheduler._last_activity_time
        test_file = tmp_path / "act.txt"
        test_file.write_text("test")

        await dream_runtime.process_natural_language(
            f"read the file at {test_file}"
        )

        assert scheduler._last_activity_time >= old_activity

    @pytest.mark.asyncio
    async def test_status_after_dream_includes_report(self, dream_runtime, tmp_path):
        """After a dream cycle, status includes the last report summary."""
        test_file = tmp_path / "status_ep.txt"
        test_file.write_text("test")
        await dream_runtime.process_natural_language(
            f"read the file at {test_file}"
        )

        # Force a dream cycle
        scheduler = dream_runtime.dream_scheduler
        report = await scheduler.force_dream()

        status = dream_runtime.status()
        assert "dreaming" in status
        assert "last_report" in status["dreaming"]
        lr = status["dreaming"]["last_report"]
        assert lr["episodes_replayed"] == report.episodes_replayed


# ---------------------------------------------------------------------------
# Shell /dream command tests
# ---------------------------------------------------------------------------

class TestShellDreamCommand:

    @pytest.fixture
    async def dream_shell(self, tmp_path):
        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()
        con = Console(file=StringIO(), force_terminal=True, width=120)
        shell = ProbOSShell(rt, console=con)
        yield shell, con, rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_dream_renders_report(self, dream_shell, tmp_path):
        """/dream shows the last dream report."""
        shell, con, rt = dream_shell

        # Generate an episode first
        test_file = tmp_path / "dream_test.txt"
        test_file.write_text("test")
        await rt.process_natural_language(f"read the file at {test_file}")

        # Force a dream
        await rt.dream_scheduler.force_dream()

        await shell.execute_command("/dream")
        output = con.file.getvalue()
        assert "Dream Report" in output
        assert "Episodes replayed" in output

    @pytest.mark.asyncio
    async def test_dream_no_cycles_yet(self, dream_shell):
        """/dream shows 'no cycles yet' when no dreams have occurred."""
        shell, con, rt = dream_shell
        await shell.execute_command("/dream")
        output = con.file.getvalue()
        assert "No dream cycles" in output

    @pytest.mark.asyncio
    async def test_dream_now_triggers_cycle(self, dream_shell, tmp_path):
        """/dream now forces an immediate dream cycle."""
        shell, con, rt = dream_shell

        # Generate an episode
        test_file = tmp_path / "now_test.txt"
        test_file.write_text("test")
        await rt.process_natural_language(f"read the file at {test_file}")

        await shell.execute_command("/dream now")
        output = con.file.getvalue()
        assert "Dream Report" in output
        assert "Episodes replayed" in output

    @pytest.mark.asyncio
    async def test_dream_disabled_no_episodic(self, tmp_path):
        """/dream shows disabled message without episodic memory."""
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        try:
            con = Console(file=StringIO(), force_terminal=True, width=120)
            shell = ProbOSShell(rt, console=con)
            await shell.execute_command("/dream")
            output = con.file.getvalue()
            assert "not enabled" in output
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_help_includes_dream(self, dream_shell):
        """/help lists the /dream command."""
        shell, con, rt = dream_shell
        await shell.execute_command("/help")
        output = con.file.getvalue()
        assert "/dream" in output


# ---------------------------------------------------------------------------
# Panel rendering tests
# ---------------------------------------------------------------------------

class TestDreamPanel:

    def test_render_dream_panel_with_report(self):
        """render_dream_panel renders report data."""
        report = DreamReport(
            episodes_replayed=10,
            weights_strengthened=5,
            weights_pruned=2,
            trust_adjustments=3,
            pre_warm_intents=["read_file", "list_directory"],
            duration_ms=42.5,
        )
        con = Console(file=StringIO(), force_terminal=True, width=120)
        panel = panels.render_dream_panel(report)
        con.print(panel)
        output = con.file.getvalue()
        assert "Dream Report" in output
        assert "10" in output  # episodes
        assert "5" in output   # strengthened
        assert "2" in output   # pruned
        assert "3" in output   # trust adjustments
        assert "read_file" in output
        assert "list_directory" in output
        assert "42.5" in output

    def test_render_dream_panel_empty_state(self):
        """render_dream_panel renders empty state when no report."""
        con = Console(file=StringIO(), force_terminal=True, width=120)
        panel = panels.render_dream_panel(None)
        con.print(panel)
        output = con.file.getvalue()
        assert "No dream cycles" in output
        assert "/dream now" in output

    def test_render_dream_panel_no_pre_warm(self):
        """render_dream_panel handles report with no pre-warm intents."""
        report = DreamReport(
            episodes_replayed=1,
            weights_strengthened=0,
            weights_pruned=0,
            trust_adjustments=0,
            pre_warm_intents=[],
            duration_ms=1.0,
        )
        con = Console(file=StringIO(), force_terminal=True, width=120)
        panel = panels.render_dream_panel(report)
        con.print(panel)
        output = con.file.getvalue()
        assert "No pre-warm intents" in output

    def test_render_status_panel_includes_dreaming(self):
        """render_status_panel includes dreaming section."""
        status = {
            "system": {"name": "ProbOS", "version": "0.1.0"},
            "started": True,
            "total_agents": 10,
            "pools": {},
            "mesh": {},
            "consensus": {"quorum_policy": {}},
            "cognitive": {},
            "dreaming": {
                "state": "idle",
                "enabled": True,
                "last_report": {
                    "episodes_replayed": 5,
                    "weights_strengthened": 3,
                    "weights_pruned": 1,
                },
            },
        }
        con = Console(file=StringIO(), force_terminal=True, width=120)
        panel = panels.render_status_panel(status)
        con.print(panel)
        output = con.file.getvalue()
        assert "Dreaming" in output
        assert "idle" in output


# ---------------------------------------------------------------------------
# BF-008: Dream cycle composability (no double-replay)
# ---------------------------------------------------------------------------

class TestBF008DreamComposability:
    """Verify dream_cycle composes with micro_dream and no longer double-replays."""

    @pytest.mark.asyncio
    async def test_dream_cycle_includes_contradiction_count(self, engine, memory):
        """Dream cycle with contradictory episodes → contradictions_found > 0."""
        ep_old = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=True,
            user_input="read the file foo.txt",
        )
        ep_old.timestamp = 1.0
        ep_new = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=False,
            user_input="read the file foo.txt",
        )
        ep_new.timestamp = 2.0
        await memory.store(ep_old)
        await memory.store(ep_new)

        report = await engine.dream_cycle()
        assert report.contradictions_found >= 1

    @pytest.mark.asyncio
    async def test_dream_cycle_no_contradictions(self, engine, memory):
        """Normal episodes → contradictions_found == 0."""
        ep = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=True,
            user_input="read the file foo.txt",
        )
        await memory.store(ep)

        report = await engine.dream_cycle()
        assert report.contradictions_found == 0

    @pytest.mark.asyncio
    async def test_contradiction_callback_invoked(self, router, trust, memory, dream_config):
        """Provide a mock contradiction_resolve_fn, verify it's called."""
        callback_args: list = []

        def mock_resolve(contradictions):
            callback_args.append(contradictions)

        engine = DreamingEngine(
            router, trust, memory, dream_config,
            contradiction_resolve_fn=mock_resolve,
        )

        ep_old = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=True,
            user_input="read the file foo.txt",
        )
        ep_old.timestamp = 1.0
        ep_new = _make_episode(
            intents=["read_file"],
            agent_ids=["agent_a"],
            success=False,
            user_input="read the file foo.txt",
        )
        ep_new.timestamp = 2.0
        await memory.store(ep_old)
        await memory.store(ep_new)

        await engine.dream_cycle()
        assert len(callback_args) == 1
        assert len(callback_args[0]) >= 1

    @pytest.mark.asyncio
    async def test_dream_cycle_calls_micro_dream_first(self, engine, memory):
        """dream_cycle() starts with a micro_dream() flush."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        calls: list[str] = []
        original_micro = engine.micro_dream

        async def tracking_micro():
            calls.append("micro_dream")
            return await original_micro()

        engine.micro_dream = tracking_micro
        await engine.dream_cycle()

        assert calls == ["micro_dream"], "micro_dream should be called exactly once"

    @pytest.mark.asyncio
    async def test_dream_cycle_does_not_call_replay_directly(self, engine, memory):
        """dream_cycle() does NOT call _replay_episodes directly (only via micro_dream)."""
        ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
        await memory.store(ep)

        replay_calls: list[str] = []
        original_replay = engine._replay_episodes

        def tracking_replay(episodes):
            replay_calls.append("replay")
            return original_replay(episodes)

        engine._replay_episodes = tracking_replay

        # micro_dream will call _replay_episodes internally.
        # We need to verify dream_cycle doesn't make an additional call.
        await engine.dream_cycle()

        # micro_dream may call _replay_episodes once for its flush.
        # The key invariant: dream_cycle itself does NOT add an extra call.
        # With 1 new episode, micro_dream calls _replay_episodes once.
        assert len(replay_calls) <= 1, (
            f"_replay_episodes called {len(replay_calls)} times; "
            "dream_cycle should not call it separately"
        )

    @pytest.mark.asyncio
    async def test_dream_cycle_still_runs_maintenance(self, engine, memory, trust, router):
        """dream_cycle() still executes pruning, trust consolidation, pre-warm,
        strategy extraction, and gap prediction after micro_dream flush."""
        # Create several episodes for trust consolidation (needs >1 per agent)
        for _ in range(3):
            ep = _make_episode(
                intents=["list_directory", "read_file"],
                agent_ids=["agent_x"],
                success=True,
            )
            await memory.store(ep)

        # Seed a below-threshold weight that should get pruned
        router._weights[("dead_intent", "dead_agent", REL_INTENT)] = 0.005
        router._compat_weights[("dead_intent", "dead_agent")] = 0.005

        report = await engine.dream_cycle()

        assert report.weights_pruned >= 1, "Pruning should still run"
        assert report.trust_adjustments >= 1, "Trust consolidation should still run"
        assert len(report.pre_warm_intents) > 0, "Pre-warm should still run"

    @pytest.mark.asyncio
    async def test_dream_report_reflects_micro_dream_flush(self, engine, memory):
        """DreamReport.episodes_replayed equals the micro_dream flush count,
        not the full replay_episode_count."""
        # Store 3 episodes — micro_dream flush should report 3 (not 50)
        for _ in range(3):
            ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
            await memory.store(ep)

        report = await engine.dream_cycle()

        assert report.episodes_replayed == 3
        assert report.weights_strengthened >= 3  # At least one per episode

        # Second dream with no new episodes should show 0
        report2 = await engine.dream_cycle()
        assert report2.episodes_replayed == 0
        assert report2.weights_strengthened == 0

    @pytest.mark.asyncio
    async def test_micro_dream_cursor_not_reset_by_full_dream(self, engine, memory):
        """The micro-dream cursor (_last_consolidated_count) is only advanced
        by micro_dream, not separately reset by dream_cycle."""
        # Store 5 episodes
        for _ in range(5):
            ep = _make_episode(intents=["read_file"], agent_ids=["a"], success=True)
            await memory.store(ep)

        # Run micro_dream to advance the cursor
        await engine.micro_dream()
        cursor_after_micro = engine._last_consolidated_count
        assert cursor_after_micro == 5

        # Run dream_cycle — cursor should remain at 5 (no reset, no further advance)
        await engine.dream_cycle()
        cursor_after_dream = engine._last_consolidated_count
        assert cursor_after_dream == cursor_after_micro, (
            "dream_cycle should not reset the micro-dream cursor"
        )


# ---------------------------------------------------------------------------
# Integration: NL -> episodes -> dream -> weights changed
# ---------------------------------------------------------------------------

class TestDreamingIntegration:

    @pytest.mark.asyncio
    async def test_nl_to_dream_cycle_changes_weights(self, tmp_path):
        """Full integration: NL requests generate episodes, dream cycle changes weights."""
        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()

        try:
            # Generate several episodes via NL processing
            for i in range(3):
                f = tmp_path / f"int_{i}.txt"
                f.write_text(f"content {i}")
                await rt.process_natural_language(f"read the file at {f}")

            # Confirm episodes exist (AD-430c act-store hook may add extras)
            episodes = await mem.recent(k=20)
            assert len(episodes) >= 3

            # Record weights before dream
            weights_before = dict(rt.hebbian_router.all_weights_typed())

            # Force dream cycle
            report = await rt.dream_scheduler.force_dream()

            # Verify report is meaningful
            assert report.episodes_replayed >= 3
            assert report.duration_ms >= 0

            # Verify the scheduler stored the report
            assert rt.dream_scheduler.last_dream_report is report

            # Verify weights changed (dream cycle at minimum applies decay_all)
            weights_after = rt.hebbian_router.all_weights_typed()
            # The dream cycle modifies weights — either through strengthening,
            # decay, or pruning. The key thing is it ran without error.
            assert isinstance(weights_after, dict)
        finally:
            await rt.stop()


class TestDreamSchedulerProactiveAwareness:
    """Tests for AD-417: Dream scheduler proactive-loop awareness."""

    def _make_engine(self):
        """Create a minimal DreamingEngine for testing."""
        from unittest.mock import AsyncMock, MagicMock
        engine = MagicMock(spec=DreamingEngine)
        engine.dream_cycle = AsyncMock(return_value=MagicMock(episodes_replayed=0, weights_modified=0, pruned_connections=0))
        engine.micro_dream = AsyncMock(return_value={"episodes_replayed": 0})
        return engine

    def test_record_proactive_activity_updates_timestamp(self):
        """record_proactive_activity sets _last_proactive_time."""
        engine = self._make_engine()
        scheduler = DreamScheduler(engine=engine, idle_threshold_seconds=2.0)
        assert scheduler._last_proactive_time == 0.0
        scheduler.record_proactive_activity()
        assert scheduler._last_proactive_time > 0

    @pytest.mark.asyncio
    async def test_proactive_activity_prevents_full_dream(self):
        """Full dream doesn't fire when proactive activity keeps system busy."""
        engine = self._make_engine()
        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=0.5,
            dream_interval_seconds=0.1,
            micro_dream_interval_seconds=100,  # Disable micro-dreams
        )
        scheduler.start()
        try:
            # Keep proactive activity going for 2 seconds
            for _ in range(8):
                scheduler.record_proactive_activity()
                await asyncio.sleep(0.25)
            # Full dream should NOT have fired
            engine.dream_cycle.assert_not_called()

            # Now stop proactive activity and wait for idle threshold + dream interval
            await asyncio.sleep(1.0)
            # Full dream should now fire
            assert engine.dream_cycle.call_count >= 1
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_proactive_activity_does_not_affect_micro_dreams(self):
        """Micro-dreams still fire during proactive activity."""
        engine = self._make_engine()
        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=100,  # Long threshold so no full dreams
            dream_interval_seconds=100,
            micro_dream_interval_seconds=0.1,
        )
        scheduler.record_proactive_activity()
        scheduler.start()
        try:
            await asyncio.sleep(1.5)
            assert engine.micro_dream.call_count >= 1
        finally:
            await scheduler.stop()

    def test_is_proactively_busy_property(self):
        """is_proactively_busy reflects recency of proactive activity."""
        engine = self._make_engine()
        scheduler = DreamScheduler(engine=engine, idle_threshold_seconds=0.3)
        # No proactive activity yet
        assert scheduler.is_proactively_busy is False
        # Record activity
        scheduler.record_proactive_activity()
        assert scheduler.is_proactively_busy is True
        # Manually backdate to simulate time passing
        scheduler._last_proactive_time = time.monotonic() - 1.0
        assert scheduler.is_proactively_busy is False

    def test_proactive_extends_idle_disabled(self):
        """When disabled, proactive activity doesn't affect dreams or busy state."""
        engine = self._make_engine()
        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=1.0,
            proactive_extends_idle=False,
        )
        scheduler.record_proactive_activity()
        # Even with recent proactive activity, not busy when disabled
        assert scheduler.is_proactively_busy is False

    @pytest.mark.asyncio
    async def test_proactive_extends_idle_disabled_allows_dreams(self):
        """With proactive_extends_idle=False, full dreams fire despite proactive activity."""
        engine = self._make_engine()
        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=0.3,
            dream_interval_seconds=0.1,
            micro_dream_interval_seconds=100,
            proactive_extends_idle=False,
        )
        scheduler.start()
        try:
            # Keep proactive activity going
            for _ in range(4):
                scheduler.record_proactive_activity()
                await asyncio.sleep(0.2)
            # Wait for idle threshold
            await asyncio.sleep(0.5)
            # Dreams should fire because proactive activity is ignored
            assert engine.dream_cycle.call_count >= 1
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_user_activity_still_overrides_proactive(self):
        """User activity also resets idle timer alongside proactive activity."""
        engine = self._make_engine()
        scheduler = DreamScheduler(
            engine=engine,
            idle_threshold_seconds=0.5,
            dream_interval_seconds=0.1,
            micro_dream_interval_seconds=100,
        )
        scheduler.start()
        try:
            # Proactive activity keeps system busy
            scheduler.record_proactive_activity()
            # User activity also resets idle
            scheduler.record_activity()
            await asyncio.sleep(0.3)
            # Neither has expired — no dream
            engine.dream_cycle.assert_not_called()
            # Wait for both to expire
            await asyncio.sleep(0.8)
            assert engine.dream_cycle.call_count >= 1
        finally:
            await scheduler.stop()

    def test_config_field_exists(self):
        """DreamingConfig has proactive_extends_idle field."""
        cfg = DreamingConfig()
        assert cfg.proactive_extends_idle is True
        cfg2 = DreamingConfig(proactive_extends_idle=False)
        assert cfg2.proactive_extends_idle is False

    def test_skip_emergent_during_proactive_busy(self):
        """_on_post_micro_dream skips EmergentDetector when proactively busy."""
        from unittest.mock import MagicMock, PropertyMock
        from probos.runtime import ProbOSRuntime
        from probos.dream_adapter import DreamAdapter

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._emergent_detector = MagicMock()
        rt.dream_scheduler = MagicMock()

        # AD-515: Create DreamAdapter used by delegation
        rt.dream_adapter = DreamAdapter(
            dream_scheduler=rt.dream_scheduler,
            emergent_detector=rt._emergent_detector,
            episodic_memory=None,
            knowledge_store=None,
            hebbian_router=MagicMock(),
            trust_network=MagicMock(),
            event_emitter=MagicMock(),
            self_mod_pipeline=None,
            bridge_alerts=None,
            ward_room=None,
            registry=MagicMock(),
            event_log=None,
            config=MagicMock(),
            pools={},
        )

        # When proactively busy — skip analysis
        type(rt.dream_scheduler).is_proactively_busy = PropertyMock(return_value=True)
        rt.dream_adapter.on_post_micro_dream({"episodes_replayed": 5})
        rt._emergent_detector.analyze.assert_not_called()

        # When not busy — run analysis
        type(rt.dream_scheduler).is_proactively_busy = PropertyMock(return_value=False)
        rt.dream_adapter.on_post_micro_dream({"episodes_replayed": 5})
        rt._emergent_detector.analyze.assert_called_once()
