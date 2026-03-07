"""Tests for CapabilityRegistry."""

import pytest

from probos.mesh.capability import CapabilityRegistry
from probos.types import CapabilityDescriptor


class TestCapabilityRegistry:
    def test_register_and_query_exact(self):
        reg = CapabilityRegistry()
        reg.register("agent-1", [
            CapabilityDescriptor(can="read_file", detail="Read files"),
        ])
        matches = reg.query("read_file")
        assert len(matches) == 1
        assert matches[0].agent_id == "agent-1"
        assert matches[0].score == 1.0

    def test_query_substring_match(self):
        reg = CapabilityRegistry()
        reg.register("agent-1", [
            CapabilityDescriptor(can="read_file"),
        ])
        matches = reg.query("read")
        assert len(matches) == 1
        assert matches[0].score == 0.8  # substring

    def test_query_keyword_match(self):
        reg = CapabilityRegistry()
        reg.register("agent-1", [
            CapabilityDescriptor(can="search_content", detail="Search within file contents"),
        ])
        matches = reg.query("file")
        assert len(matches) == 1
        assert matches[0].score > 0.0
        assert matches[0].score <= 0.5

    def test_query_no_match(self):
        reg = CapabilityRegistry()
        reg.register("agent-1", [
            CapabilityDescriptor(can="read_file"),
        ])
        matches = reg.query("send_email")
        assert len(matches) == 0

    def test_multiple_agents(self):
        reg = CapabilityRegistry()
        reg.register("agent-1", [CapabilityDescriptor(can="read_file")])
        reg.register("agent-2", [CapabilityDescriptor(can="read_file")])
        reg.register("agent-3", [CapabilityDescriptor(can="write_file")])

        matches = reg.query("read_file")
        # agent-1 and agent-2 are exact matches (score 1.0)
        # agent-3 has keyword overlap ("file") so it appears as a partial match
        exact = [m for m in matches if m.score == 1.0]
        assert len(exact) == 2
        assert {m.agent_id for m in exact} == {"agent-1", "agent-2"}

    def test_unregister(self):
        reg = CapabilityRegistry()
        reg.register("agent-1", [CapabilityDescriptor(can="read_file")])
        reg.unregister("agent-1")
        matches = reg.query("read_file")
        assert len(matches) == 0
        assert reg.agent_count == 0

    def test_get_agent_capabilities(self):
        reg = CapabilityRegistry()
        caps = [CapabilityDescriptor(can="a"), CapabilityDescriptor(can="b")]
        reg.register("agent-1", caps)
        result = reg.get_agent_capabilities("agent-1")
        assert len(result) == 2
        assert result[0].can == "a"

    def test_results_sorted_by_score(self):
        reg = CapabilityRegistry()
        reg.register("exact", [CapabilityDescriptor(can="read_file")])
        reg.register("partial", [CapabilityDescriptor(can="read_file_async")])
        matches = reg.query("read_file")
        assert len(matches) == 2
        assert matches[0].agent_id == "exact"  # Score 1.0 > 0.8
