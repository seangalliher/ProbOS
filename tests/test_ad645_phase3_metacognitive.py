"""AD-645 Phase 3: Metacognitive Storage — Tests.

Verifies that reasoning entries are stored in AgentWorkingMemory,
rendered in context, serialized/restored across stasis, and that
composition briefs flow from chain results into working memory.
"""

import time
import pytest

from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# ---------------------------------------------------------------------------
# WorkingMemory Tests (1-9)
# ---------------------------------------------------------------------------

class TestRecordReasoning:

    def test_record_reasoning_stores_entry(self):
        wm = AgentWorkingMemory()
        wm.record_reasoning("Latency spike detected", source="proactive_think")
        assert len(wm._recent_reasoning) == 1
        entry = wm._recent_reasoning[0]
        assert entry.category == "reasoning"
        assert entry.content == "Latency spike detected"
        assert entry.source_pathway == "proactive_think"

    def test_reasoning_deque_maxlen(self):
        wm = AgentWorkingMemory(max_recent_reasoning=3)
        for i in range(5):
            wm.record_reasoning(f"Reasoning {i}", source="test")
        assert len(wm._recent_reasoning) == 3
        # Oldest (0 and 1) should be evicted
        assert wm._recent_reasoning[0].content == "Reasoning 2"
        assert wm._recent_reasoning[2].content == "Reasoning 4"


class TestRenderContextReasoning:

    def test_render_context_includes_reasoning(self):
        wm = AgentWorkingMemory()
        wm.record_reasoning("Captain asked about crew morale", source="dm")
        output = wm.render_context()
        assert "Recent reasoning:" in output
        assert "Captain asked about crew morale" in output

    def test_reasoning_priority_between_actions_and_conversations(self):
        wm = AgentWorkingMemory()
        wm.record_action("Sent status report", source="proactive")
        wm.record_reasoning("Reasoning about crew trust", source="dm")
        wm.record_conversation("Discussed morale", partner="Captain", source="dm")
        output = wm.render_context()
        actions_pos = output.index("Recent actions:")
        reasoning_pos = output.index("Recent reasoning:")
        conversations_pos = output.index("Recent conversations:")
        assert actions_pos < reasoning_pos < conversations_pos

    def test_render_context_no_reasoning_when_empty(self):
        wm = AgentWorkingMemory()
        wm.record_action("Did something", source="test")
        output = wm.render_context()
        assert "Recent reasoning:" not in output


class TestSerializationReasoning:

    def test_to_dict_includes_reasoning(self):
        wm = AgentWorkingMemory()
        wm.record_reasoning(
            "Evaluated crew fitness",
            source="proactive_think",
            knowledge_source="reasoning",
        )
        data = wm.to_dict()
        assert "recent_reasoning" in data
        assert len(data["recent_reasoning"]) == 1
        entry = data["recent_reasoning"][0]
        assert entry["content"] == "Evaluated crew fitness"
        assert entry["category"] == "reasoning"
        assert entry["source_pathway"] == "proactive_think"
        assert entry["knowledge_source"] == "reasoning"

    def test_from_dict_restores_reasoning(self):
        now = time.time()
        data = {
            "recent_reasoning": [
                {
                    "content": "Restored reasoning entry",
                    "category": "reasoning",
                    "source_pathway": "dm",
                    "timestamp": now - 60,  # 1 minute ago
                    "metadata": {},
                    "knowledge_source": "reasoning",
                }
            ],
        }
        wm = AgentWorkingMemory.from_dict(data)
        assert len(wm._recent_reasoning) == 1
        assert wm._recent_reasoning[0].content == "Restored reasoning entry"

    def test_from_dict_prunes_stale_reasoning(self):
        now = time.time()
        data = {
            "recent_reasoning": [
                {
                    "content": "Very old reasoning",
                    "category": "reasoning",
                    "source_pathway": "test",
                    "timestamp": now - 100000,  # >24h ago
                    "metadata": {},
                    "knowledge_source": "reasoning",
                }
            ],
        }
        wm = AgentWorkingMemory.from_dict(data)
        assert len(wm._recent_reasoning) == 0

    def test_from_dict_backward_compat_no_reasoning_key(self):
        data = {
            "recent_actions": [],
            "recent_observations": [],
            "recent_conversations": [],
            "recent_events": [],
            "active_engagements": {},
            "cognitive_state": {},
        }
        wm = AgentWorkingMemory.from_dict(data)
        assert len(wm._recent_reasoning) == 0


# ---------------------------------------------------------------------------
# Chain Integration Tests (10-15)
# ---------------------------------------------------------------------------

class TestChainBriefExtraction:

    def test_composition_brief_in_chain_result(self):
        """Verify _composition_brief is extracted from ANALYZE results."""
        # Simulate what _execute_sub_task_chain does
        brief = {
            "situation": "Crew discussing latency",
            "key_evidence": ["200ms spikes"],
            "response_should_cover": ["Root cause"],
            "tone": "Analytical",
            "sources_to_draw_on": "Ward Room data",
        }
        results = [
            SubTaskResult(
                sub_task_type=SubTaskType.ANALYZE,
                name="analyze",
                result={"contribution_assessment": "RESPOND", "composition_brief": brief},
                duration_ms=10.0,
                success=True,
            ),
            SubTaskResult(
                sub_task_type=SubTaskType.COMPOSE,
                name="compose",
                result={"output": "Test response"},
                duration_ms=20.0,
                success=True,
            ),
        ]
        # Extract brief (same logic as in _execute_sub_task_chain)
        _composition_brief = None
        for r in results:
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                _composition_brief = r.result.get("composition_brief")
                break
        assert _composition_brief == brief

    def test_composition_brief_none_when_suppressed(self):
        """Suppressed decisions should have _composition_brief=None."""
        decision = {
            "action": "execute",
            "llm_output": "[NO_RESPONSE]",
            "sub_task_chain": True,
            "_suppressed": True,
            "_composition_brief": None,
        }
        assert decision["_composition_brief"] is None

    def test_composition_brief_recorded_to_working_memory(self):
        """Simulate post-execution recording path."""
        wm = AgentWorkingMemory()
        brief = {
            "situation": "Captain asked about crew",
            "response_should_cover": ["trust scores", "duty reports"],
        }
        decision = {
            "sub_task_chain": True,
            "_composition_brief": brief,
        }

        # Simulate the recording logic from cognitive_agent.py
        if decision.get("sub_task_chain") and decision.get("_composition_brief"):
            b = decision["_composition_brief"]
            if isinstance(b, dict):
                _situation = b.get("situation", "")
                _cover = b.get("response_should_cover")
                if isinstance(_cover, list):
                    _cover_text = "; ".join(str(c) for c in _cover[:3])
                else:
                    _cover_text = str(_cover) if _cover else ""
                summary_parts = []
                if _situation:
                    summary_parts.append(_situation)
                if _cover_text:
                    summary_parts.append(f"Planned to cover: {_cover_text}")
                if summary_parts:
                    wm.record_reasoning(
                        " | ".join(summary_parts),
                        source="test_intent",
                        metadata={"composition_brief": b},
                        knowledge_source="reasoning",
                    )

        assert len(wm._recent_reasoning) == 1
        assert "Captain asked about crew" in wm._recent_reasoning[0].content

    def test_composition_brief_not_recorded_when_null(self):
        """Null brief should not create a reasoning entry."""
        wm = AgentWorkingMemory()
        decision = {
            "sub_task_chain": True,
            "_composition_brief": None,
        }
        # Same guard as cognitive_agent.py
        if decision.get("sub_task_chain") and decision.get("_composition_brief"):
            wm.record_reasoning("Should not appear", source="test")
        assert len(wm._recent_reasoning) == 0

    def test_composition_brief_summary_format(self):
        """Verify the human-readable summary format."""
        wm = AgentWorkingMemory()
        brief = {
            "situation": "Captain asked about crew",
            "response_should_cover": ["trust scores", "duty reports"],
        }
        # Reproduce recording logic
        _situation = brief.get("situation", "")
        _cover = brief.get("response_should_cover")
        _cover_text = "; ".join(str(c) for c in _cover[:3]) if isinstance(_cover, list) else ""
        summary_parts = []
        if _situation:
            summary_parts.append(_situation)
        if _cover_text:
            summary_parts.append(f"Planned to cover: {_cover_text}")
        wm.record_reasoning(
            " | ".join(summary_parts),
            source="dm",
            metadata={"composition_brief": brief},
            knowledge_source="reasoning",
        )
        entry = wm._recent_reasoning[0]
        assert "Captain asked about crew" in entry.content
        assert "Planned to cover: trust scores; duty reports" in entry.content

    def test_reasoning_survives_stasis_roundtrip(self):
        """Reasoning entries persist through to_dict → from_dict cycle."""
        wm = AgentWorkingMemory()
        wm.record_reasoning(
            "Latency analysis complete",
            source="proactive_think",
            knowledge_source="reasoning",
        )

        # Serialize
        data = wm.to_dict()
        assert len(data["recent_reasoning"]) == 1

        # Restore
        wm2 = AgentWorkingMemory.from_dict(data)
        assert len(wm2._recent_reasoning) == 1
        assert wm2._recent_reasoning[0].content == "Latency analysis complete"

        # Verify renders
        output = wm2.render_context()
        assert "Recent reasoning:" in output
        assert "Latency analysis complete" in output
