"""Tests for Phase 6b: Dynamic Intent Discovery — Runtime integration."""

import pytest

from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CustomTestAgent(BaseAgent):
    """A test-only agent with a custom intent descriptor."""

    agent_type: str = "custom_test"
    default_capabilities = [
        CapabilityDescriptor(can="custom_greeting", detail="Generate a greeting"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="custom_greeting",
            params={"name": "..."},
            description="Generate a greeting",
        ),
    ]
    initial_confidence: float = 0.8
    _handled_intents = {"custom_greeting"}

    async def perceive(self, intent: dict) -> dict | None:
        if intent.get("intent") not in self._handled_intents:
            return None
        return {"intent": intent["intent"], "params": intent.get("params", {})}

    async def decide(self, observation):
        return {"action": "greet", "params": observation["params"]}

    async def act(self, plan):
        name = plan["params"].get("name", "world")
        return {"success": True, "data": f"Hello, {name}!"}

    async def report(self, result):
        return result


# ---------------------------------------------------------------------------
# Runtime integration tests
# ---------------------------------------------------------------------------

class TestRuntimeDiscovery:

    @pytest.fixture
    async def rt(self, tmp_path):
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
    async def test_runtime_collects_descriptors_at_boot(self, rt):
        """After start(), decomposer._intent_descriptors is non-empty."""
        descs = rt.decomposer._intent_descriptors
        assert len(descs) > 0
        names = {d.name for d in descs}
        for expected in ["read_file", "write_file", "run_command"]:
            assert expected in names, f"{expected!r} not in collected descriptors"

    @pytest.mark.asyncio
    async def test_runtime_descriptors_deduplicated(self, rt):
        """_collect_intent_descriptors returns each intent name only once."""
        descs = rt._collect_intent_descriptors()
        names = [d.name for d in descs]
        assert len(names) == len(set(names)), "Duplicate intent names found"

    @pytest.mark.asyncio
    async def test_register_agent_type_refreshes_decomposer(self, rt):
        """register_agent_type() refreshes decomposer descriptors."""
        # Before registration
        names_before = {d.name for d in rt.decomposer._intent_descriptors}
        assert "custom_greeting" not in names_before

        rt.register_agent_type("custom_test", CustomTestAgent)

        names_after = {d.name for d in rt.decomposer._intent_descriptors}
        assert "custom_greeting" in names_after

    @pytest.mark.asyncio
    async def test_existing_nl_processing_unchanged(self, rt, tmp_path):
        """Full NL pipeline still works with dynamic discovery."""
        test_file = tmp_path / "data" / "test_read.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("hello world")

        result = await rt.process_natural_language(
            f"read the file at {test_file}"
        )
        assert result is not None
        assert result.get("node_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_dynamic_discovery_end_to_end(self, rt):
        """Register a custom agent type, verify decomposer knows about it."""
        rt.register_agent_type("custom_test", CustomTestAgent)

        # The decomposer's system prompt now contains custom_greeting
        prompt = rt.decomposer._prompt_builder.build_system_prompt(
            rt.decomposer._intent_descriptors
        )
        assert "custom_greeting" in prompt
        assert "Generate a greeting" in prompt
