"""Phase 14d — Agent Tier Classification tests."""

from __future__ import annotations

import pytest

from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor


# ===================================================================
# 1. Default tier
# ===================================================================


class TestDefaultTier:
    """BaseAgent default tier is 'domain'."""

    def test_base_agent_default_tier(self):
        assert BaseAgent.tier == "domain"


# ===================================================================
# 2. Agent tier classification
# ===================================================================


class TestAgentTiers:
    """Every agent has the correct tier."""

    def test_file_reader_tier(self):
        from probos.agents.file_reader import FileReaderAgent
        assert FileReaderAgent.tier == "core"

    def test_file_writer_tier(self):
        from probos.agents.file_writer import FileWriterAgent
        assert FileWriterAgent.tier == "core"

    def test_directory_list_tier(self):
        from probos.agents.directory_list import DirectoryListAgent
        assert DirectoryListAgent.tier == "core"

    def test_file_search_tier(self):
        from probos.agents.file_search import FileSearchAgent
        assert FileSearchAgent.tier == "core"

    def test_shell_command_tier(self):
        from probos.agents.shell_command import ShellCommandAgent
        assert ShellCommandAgent.tier == "core"

    def test_http_fetch_tier(self):
        from probos.agents.http_fetch import HttpFetchAgent
        assert HttpFetchAgent.tier == "core"

    def test_red_team_tier(self):
        from probos.agents.red_team import RedTeamAgent
        assert RedTeamAgent.tier == "core"

    def test_heartbeat_tier(self):
        from probos.substrate.heartbeat import HeartbeatAgent
        assert HeartbeatAgent.tier == "core"

    def test_system_heartbeat_tier(self):
        from probos.agents.heartbeat_monitor import SystemHeartbeatAgent
        assert SystemHeartbeatAgent.tier == "core"

    def test_introspection_tier(self):
        from probos.agents.introspect import IntrospectionAgent
        assert IntrospectionAgent.tier == "utility"

    def test_system_qa_tier(self):
        from probos.agents.system_qa import SystemQAAgent
        assert SystemQAAgent.tier == "utility"

    def test_skill_based_tier(self):
        from probos.substrate.skill_agent import SkillBasedAgent
        assert SkillBasedAgent.tier == "domain"

    def test_corrupted_tier(self):
        from probos.agents.corrupted import CorruptedFileReaderAgent
        assert CorruptedFileReaderAgent.tier == "core"


# ===================================================================
# 3. IntentDescriptor tier field
# ===================================================================


class TestIntentDescriptorTier:
    """IntentDescriptor includes a tier field."""

    def test_default_tier_is_domain(self):
        desc = IntentDescriptor(name="test_intent")
        assert desc.tier == "domain"

    def test_tier_can_be_set(self):
        desc = IntentDescriptor(name="test_intent", tier="core")
        assert desc.tier == "core"


# ===================================================================
# 4. Manifest includes tier
# ===================================================================


class TestManifestTier:
    """Agent manifest entries include tier field."""

    @pytest.mark.asyncio
    async def test_manifest_has_tier(self, tmp_path):
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        manifest = rt._build_manifest()
        assert len(manifest) > 0
        for entry in manifest:
            assert "tier" in entry, f"Missing tier in manifest entry: {entry}"
        await rt.stop()


# ===================================================================
# 5. Agent table panel includes Tier column
# ===================================================================


class TestPanelTier:
    """Agent table panel renders Tier column."""

    def test_agent_table_has_tier_column(self):
        from probos.experience.panels import render_agent_table
        from probos.types import AgentState

        class MockAgent:
            id = "abc123"
            agent_type = "file_reader"
            tier = "core"
            pool = "filesystem"
            state = AgentState.ACTIVE
            confidence = 0.9

        table = render_agent_table([MockAgent()], {"abc123": 0.85})
        # Check columns contain "Tier"
        col_names = [c.header for c in table.columns]
        assert "Tier" in col_names


# ===================================================================
# 6. Descriptor collection
# ===================================================================


class TestDescriptorCollection:
    """_collect_intent_descriptors is based on non-empty descriptors."""

    def test_excluded_agent_types_removed(self):
        """_EXCLUDED_AGENT_TYPES should not exist on ProbOSRuntime."""
        from probos.runtime import ProbOSRuntime
        assert not hasattr(ProbOSRuntime, "_EXCLUDED_AGENT_TYPES")

    @pytest.mark.asyncio
    async def test_includes_utility_with_descriptors(self, tmp_path):
        """IntrospectionAgent (utility tier) descriptors are included."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        descriptors = rt._collect_intent_descriptors()
        names = [d.name for d in descriptors]
        # IntrospectionAgent's intents should be present
        assert "explain_last" in names
        assert "agent_info" in names
        assert "system_health" in names
        assert "introspect_memory" in names
        assert "introspect_system" in names

    @pytest.mark.asyncio
    async def test_excludes_empty_descriptors(self, tmp_path):
        """Agents with empty intent_descriptors are excluded regardless of tier."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.llm_client import MockLLMClient

        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
        descriptors = rt._collect_intent_descriptors()
        names = [d.name for d in descriptors]
        # SystemQAAgent has empty descriptors — smoke_test_agent should not appear
        assert "smoke_test_agent" not in names
        # RedTeamAgent has empty descriptors — no red team intents
        assert all("red_team" not in n for n in names)
