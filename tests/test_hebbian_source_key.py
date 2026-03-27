"""BF-044: Verify Hebbian routing uses intent name (not msg UUID) as source key."""

import re
import pytest

from probos.runtime import ProbOSRuntime


@pytest.fixture
async def runtime(tmp_path):
    """Minimal runtime with temp data dir and a real file to read."""
    # Create a file the read_file agent can successfully read
    target = tmp_path / "data" / "readable.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello world")

    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    await rt.start()
    yield rt, str(target)
    await rt.stop()


class TestHebbianSourceKey:
    @pytest.mark.asyncio
    async def test_hebbian_uses_intent_name_as_source(self, runtime):
        """submit_intent should record Hebbian weight keyed by intent name, not msg UUID."""
        rt, filepath = runtime
        results = await rt.submit_intent("read_file", params={"path": filepath})
        if not results:
            pytest.skip("No agent handled the intent")

        agent_id = results[0].agent_id
        # Weight should be keyed by "read_file" (the intent name)
        weight = rt.hebbian_router.get_weight("read_file", agent_id)
        assert weight != 0.0, "Hebbian weight should be recorded with intent name as source"

    @pytest.mark.asyncio
    async def test_hebbian_reinforcement_across_calls(self, runtime):
        """Repeated same-intent calls should reinforce the Hebbian weight."""
        rt, filepath = runtime

        # First call
        results1 = await rt.submit_intent("read_file", params={"path": filepath})
        if not results1:
            pytest.skip("No agent handled the intent")
        agent_id = results1[0].agent_id
        weight1 = rt.hebbian_router.get_weight("read_file", agent_id)

        # Second call — same intent name
        await rt.submit_intent("read_file", params={"path": filepath})
        weight2 = rt.hebbian_router.get_weight("read_file", agent_id)

        # Weight should change (reinforcement or decay+reward)
        assert weight2 != weight1, (
            f"Second call should change Hebbian weight (was {weight1}, now {weight2})"
        )

    @pytest.mark.asyncio
    async def test_hebbian_consensus_uses_intent_name(self, runtime):
        """submit_intent_with_consensus should also use intent name as source."""
        rt, filepath = runtime
        result = await rt.submit_intent_with_consensus(
            "read_file", params={"path": filepath}
        )
        agent_results = result.get("results", [])
        if not agent_results:
            pytest.skip("No agent handled the consensus intent")

        agent_id = agent_results[0].agent_id
        weight = rt.hebbian_router.get_weight("read_file", agent_id)
        assert weight != 0.0, "Consensus path should record weight with intent name"

    @pytest.mark.asyncio
    async def test_hebbian_event_emits_intent_name(self, runtime):
        """The hebbian_update event should contain the intent name, not a UUID."""
        rt, filepath = runtime
        events_captured = []
        original_emit = rt._emit_event

        def capture_emit(event_type, payload):
            if event_type == "hebbian_update":
                events_captured.append(payload)
            original_emit(event_type, payload)

        rt._emit_event = capture_emit

        results = await rt.submit_intent("read_file", params={"path": filepath})
        if not results:
            pytest.skip("No agent handled the intent")

        assert len(events_captured) > 0, "Should have emitted hebbian_update events"
        for evt in events_captured:
            source = evt["source"]
            # Should be "read_file", not a UUID pattern
            assert source == "read_file", f"Event source should be intent name, got '{source}'"
            uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-')
            assert not uuid_pattern.match(source), f"Source looks like a UUID: {source}"
