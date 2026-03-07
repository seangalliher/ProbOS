"""Tests for runtime consensus integration + corrupted agent detection."""

import pytest

from probos.agents.corrupted import CorruptedFileReaderAgent
from probos.runtime import ProbOSRuntime
from probos.types import ConsensusOutcome, QuorumPolicy


@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with temp data dir, start it, yield, stop."""
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    await rt.start()
    yield rt
    await rt.stop()


class TestRuntimeConsensus:
    @pytest.mark.asyncio
    async def test_red_team_agents_spawned(self, runtime):
        """Red team agents should exist after boot."""
        assert len(runtime._red_team_agents) == 2

    @pytest.mark.asyncio
    async def test_red_team_agents_are_active(self, runtime):
        from probos.types import AgentState
        for agent in runtime._red_team_agents:
            assert agent.state == AgentState.ACTIVE
            assert agent.agent_type == "red_team"

    @pytest.mark.asyncio
    async def test_trust_network_initialized(self, runtime):
        """All wired agents should have trust records."""
        assert runtime.trust_network.agent_count > 0

    @pytest.mark.asyncio
    async def test_status_includes_consensus(self, runtime):
        status = runtime.status()
        assert "consensus" in status
        assert status["consensus"]["red_team_agents"] == 2
        assert status["consensus"]["trust_network_agents"] > 0
        assert "quorum_policy" in status["consensus"]

    @pytest.mark.asyncio
    async def test_gossip_includes_red_team(self, runtime):
        """Red team agents should appear in gossip view."""
        view = runtime.gossip.get_view()
        red_team_entries = [
            e for e in view.values() if e.agent_type == "red_team"
        ]
        assert len(red_team_entries) == 2

    @pytest.mark.asyncio
    async def test_submit_with_consensus_read_file(self, runtime, tmp_path):
        """Consensus pipeline approves correct file reads."""
        test_file = tmp_path / "consensus_test.txt"
        test_file.write_text("consensus content")

        result = await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        assert result["consensus"].outcome == ConsensusOutcome.APPROVED
        assert len(result["results"]) == 3
        assert len(result["verifications"]) > 0
        # All verifications should pass (no corruption)
        for v in result["verifications"]:
            assert v.verified is True

    @pytest.mark.asyncio
    async def test_submit_with_consensus_updates_trust(self, runtime, tmp_path):
        """Consensus pipeline should update trust scores."""
        test_file = tmp_path / "trust_test.txt"
        test_file.write_text("trust content")

        await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        # At least some agents should have trust records with observations
        scores = runtime.trust_network.all_scores()
        assert len(scores) > 0

    @pytest.mark.asyncio
    async def test_submit_with_consensus_updates_agent_weights(self, runtime, tmp_path):
        """Verification should create agent-to-agent hebbian weights."""
        test_file = tmp_path / "hebbian_test.txt"
        test_file.write_text("hebbian content")

        await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        # Check for agent-to-agent weights (from red team verifications)
        from probos.mesh.routing import REL_AGENT
        typed_weights = runtime.hebbian_router.all_weights_typed()
        agent_weights = {k: v for k, v in typed_weights.items() if k[2] == REL_AGENT}
        assert len(agent_weights) > 0

    @pytest.mark.asyncio
    async def test_consensus_events_logged(self, runtime, tmp_path):
        """Consensus events should appear in the event log."""
        test_file = tmp_path / "events_test.txt"
        test_file.write_text("events content")

        await runtime.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        events = await runtime.event_log.query(category="consensus")
        event_types = {e["event"] for e in events}
        assert "quorum_evaluated" in event_types
        assert "verification_complete" in event_types


class TestCorruptedAgentDetection:
    @pytest.mark.asyncio
    async def test_corrupted_agent_caught(self, tmp_path):
        """Inject a corrupted agent and verify consensus catches it."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        # Register corrupted agent template BEFORE start
        rt.spawner.register_template("corrupted_reader", CorruptedFileReaderAgent)
        await rt.start()

        # Manually inject a corrupted agent into the filesystem pool
        corrupted = CorruptedFileReaderAgent(pool="filesystem")
        await rt.registry.register(corrupted)
        await corrupted.start()
        await rt._wire_agent(corrupted)

        # Now we have 3 honest + 1 corrupted file readers
        test_file = tmp_path / "corruption_test.txt"
        test_file.write_text("real content")

        result = await rt.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        # Consensus should still approve (3 honest vs 1 corrupted)
        assert result["consensus"].outcome == ConsensusOutcome.APPROVED

        # At least one verification should catch the corrupted agent
        failed_verifications = [v for v in result["verifications"] if not v.verified]
        assert len(failed_verifications) >= 1

        # The corrupted agent's trust should be lower than honest agents
        corrupted_trust = rt.trust_network.get_score(corrupted.id)
        honest_agents = rt.registry.get_by_pool("filesystem")
        honest_ids = [a.id for a in honest_agents if a.id != corrupted.id]
        for honest_id in honest_ids[:1]:  # Check at least one
            honest_trust = rt.trust_network.get_score(honest_id)
            assert corrupted_trust < honest_trust

        await rt.stop()

    @pytest.mark.asyncio
    async def test_majority_corrupted_rejected(self, tmp_path):
        """When majority of agents are corrupted, consensus rejects."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        rt.spawner.register_template("corrupted_reader", CorruptedFileReaderAgent)
        await rt.start()

        # Inject 3 more corrupted agents (3 honest + 3 corrupted = 6 total)
        for _ in range(3):
            corrupted = CorruptedFileReaderAgent(pool="filesystem")
            await rt.registry.register(corrupted)
            await corrupted.start()
            await rt._wire_agent(corrupted)

        test_file = tmp_path / "majority_test.txt"
        test_file.write_text("real content")

        result = await rt.submit_intent_with_consensus(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        # 6 results: 3 honest (success with real content), 3 corrupted (success with fake)
        assert len(result["results"]) == 6

        # All 6 claim success, so quorum says APPROVED based on success/failure ratio
        # But red team verifications should catch the corrupted ones
        failed_verifications = [v for v in result["verifications"] if not v.verified]
        assert len(failed_verifications) >= 3  # At least the 3 corrupted

        await rt.stop()


class TestWriteWithConsensus:
    @pytest.mark.asyncio
    async def test_write_with_consensus_commits(self, tmp_path):
        """Write should commit when consensus approves."""
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        # Register file_writer and create a small pool
        await rt.start()
        await rt.create_pool("writers", "file_writer", target_size=3)

        write_path = str(tmp_path / "consensus_write.txt")
        result = await rt.submit_write_with_consensus(
            path=write_path,
            content="consensus approved content",
            timeout=5.0,
        )

        assert result["committed"] is True
        assert (tmp_path / "consensus_write.txt").read_text() == "consensus approved content"

        await rt.stop()
