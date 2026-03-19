"""Tests for intent decomposition and DAG execution."""

import json

import pytest

from probos.cognitive.decomposer import IntentDecomposer, DAGExecutor
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.types import IntentDescriptor, LLMRequest, LLMResponse, TaskDAG, TaskNode


class TestIntentDecomposer:
    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager()

    @pytest.fixture
    def decomposer(self, llm, wm):
        return IntentDecomposer(llm_client=llm, working_memory=wm)

    @pytest.mark.asyncio
    async def test_single_read_intent(self, decomposer):
        dag = await decomposer.decompose("read the file at /tmp/test.txt")
        assert len(dag.nodes) == 1
        node = dag.nodes[0]
        assert node.intent == "read_file"
        assert node.params["path"] == "/tmp/test.txt"
        assert not node.use_consensus

    @pytest.mark.asyncio
    async def test_parallel_reads(self, decomposer):
        dag = await decomposer.decompose("read /tmp/a.txt and /tmp/b.txt")
        assert len(dag.nodes) == 2
        paths = {n.params["path"] for n in dag.nodes}
        assert "/tmp/a.txt" in paths
        assert "/tmp/b.txt" in paths
        # Both should be independent
        for node in dag.nodes:
            assert node.depends_on == []

    @pytest.mark.asyncio
    async def test_write_with_consensus(self, decomposer):
        dag = await decomposer.decompose("write hello to /tmp/out.txt")
        assert len(dag.nodes) == 1
        node = dag.nodes[0]
        assert node.intent == "write_file"
        assert node.use_consensus is True

    @pytest.mark.asyncio
    async def test_source_text_preserved(self, decomposer):
        text = "read /tmp/test.txt"
        dag = await decomposer.decompose(text)
        assert dag.source_text == text

    @pytest.mark.asyncio
    async def test_with_context(self, decomposer):
        context = WorkingMemorySnapshot(
            capabilities=["read_file", "write_file"],
            agent_summary={"total": 5, "pools": {}},
        )
        dag = await decomposer.decompose(
            "read the file at /tmp/test.txt",
            context=context,
        )
        assert len(dag.nodes) == 1

    @pytest.mark.asyncio
    async def test_unrecognized_input_returns_empty_dag(self, decomposer):
        dag = await decomposer.decompose("what is the meaning of life?")
        assert len(dag.nodes) == 0
        assert dag.source_text == "what is the meaning of life?"

    @pytest.mark.asyncio
    async def test_malformed_json_returns_empty_dag(self, decomposer, llm):
        llm.set_default_response("this is not json at all")
        dag = await decomposer.decompose("something random")
        assert len(dag.nodes) == 0

    @pytest.mark.asyncio
    async def test_missing_intents_key(self, decomposer, llm):
        llm.set_default_response('{"data": "no intents key"}')
        dag = await decomposer.decompose("something random")
        assert len(dag.nodes) == 0

    @pytest.mark.asyncio
    async def test_intents_not_a_list(self, decomposer, llm):
        llm.set_default_response('{"intents": "not a list"}')
        dag = await decomposer.decompose("something random")
        assert len(dag.nodes) == 0

    @pytest.mark.asyncio
    async def test_empty_intent_filtered(self, decomposer, llm):
        """Intents with no intent name should be filtered out."""
        llm.set_default_response(json.dumps({
            "intents": [
                {"id": "t1", "intent": "", "params": {}, "depends_on": []},
                {"id": "t2", "intent": "read_file", "params": {"path": "/tmp/a.txt"}, "depends_on": []},
            ]
        }))
        dag = await decomposer.decompose("something")
        assert len(dag.nodes) == 1
        assert dag.nodes[0].intent == "read_file"


class TestParseResponse:
    @pytest.fixture
    def decomposer(self):
        return IntentDecomposer(
            llm_client=MockLLMClient(),
            working_memory=WorkingMemoryManager(),
        )

    def test_parse_raw_json(self, decomposer):
        content = '{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/x"}, "depends_on": [], "use_consensus": false}]}'
        dag = decomposer._parse_response(content, "test")
        assert len(dag.nodes) == 1

    def test_parse_json_in_code_block(self, decomposer):
        content = '```json\n{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/x"}, "depends_on": []}]}\n```'
        dag = decomposer._parse_response(content, "test")
        assert len(dag.nodes) == 1

    def test_parse_json_with_preamble(self, decomposer):
        content = 'Here is the result:\n{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/x"}, "depends_on": []}]}'
        dag = decomposer._parse_response(content, "test")
        assert len(dag.nodes) == 1

    def test_invalid_json_returns_empty(self, decomposer):
        dag = decomposer._parse_response("not json", "test")
        assert len(dag.nodes) == 0

    def test_non_dict_items_skipped(self, decomposer):
        content = json.dumps({
            "intents": [
                "not a dict",
                {"id": "t1", "intent": "read_file", "params": {"path": "/tmp/a"}, "depends_on": []},
                42,
            ]
        })
        dag = decomposer._parse_response(content, "test")
        assert len(dag.nodes) == 1


class TestExtractJson:
    @pytest.fixture
    def decomposer(self):
        return IntentDecomposer(
            llm_client=MockLLMClient(),
            working_memory=WorkingMemoryManager(),
        )

    def test_raw_json(self, decomposer):
        result = decomposer._extract_json('{"key": "value"}')
        assert json.loads(result) == {"key": "value"}

    def test_code_block(self, decomposer):
        result = decomposer._extract_json('```json\n{"key": "value"}\n```')
        assert json.loads(result) == {"key": "value"}

    def test_embedded_json(self, decomposer):
        result = decomposer._extract_json('Some text {"key": "value"} more text')
        assert json.loads(result) == {"key": "value"}

    def test_no_json_raises(self, decomposer):
        with pytest.raises(ValueError, match="No JSON"):
            decomposer._extract_json("no json here")


class TestTaskDAGStructure:
    def test_get_ready_nodes_all_independent(self):
        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="read_file", params={"path": "/a"}),
            TaskNode(id="t2", intent="read_file", params={"path": "/b"}),
        ])
        ready = dag.get_ready_nodes()
        assert len(ready) == 2

    def test_get_ready_nodes_with_dependency(self):
        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="read_file", params={"path": "/a"}),
            TaskNode(id="t2", intent="write_file", params={"path": "/b"}, depends_on=["t1"]),
        ])
        ready = dag.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "t1"

    def test_get_ready_after_completion(self):
        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="read_file", params={"path": "/a"}, status="completed"),
            TaskNode(id="t2", intent="write_file", params={"path": "/b"}, depends_on=["t1"]),
        ])
        ready = dag.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "t2"

    def test_is_complete(self):
        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="read_file", status="completed"),
            TaskNode(id="t2", intent="read_file", status="failed"),
        ])
        assert dag.is_complete()

    def test_is_not_complete(self):
        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="read_file", status="completed"),
            TaskNode(id="t2", intent="read_file", status="pending"),
        ])
        assert not dag.is_complete()

    def test_get_node(self):
        dag = TaskDAG(nodes=[
            TaskNode(id="t1", intent="read_file"),
            TaskNode(id="t2", intent="write_file"),
        ])
        assert dag.get_node("t1").intent == "read_file"
        assert dag.get_node("t2").intent == "write_file"
        assert dag.get_node("t99") is None

    def test_empty_dag_is_complete(self):
        dag = TaskDAG()
        assert dag.is_complete()

    def test_response_field_default_empty(self):
        dag = TaskDAG()
        assert dag.response == ""

    def test_response_field_set(self):
        dag = TaskDAG(response="Hello from ProbOS!")
        assert dag.response == "Hello from ProbOS!"


class TestResponseFieldParsing:
    """Test that the 'response' field is extracted from LLM JSON output."""

    @pytest.fixture
    def decomposer(self):
        return IntentDecomposer(
            llm_client=MockLLMClient(),
            working_memory=WorkingMemoryManager(),
        )

    def test_response_field_extracted(self, decomposer):
        content = json.dumps({
            "intents": [],
            "response": "Hello! I can read and write files.",
        })
        dag = decomposer._parse_response(content, "hello")
        assert dag.response == "Hello! I can read and write files."
        assert len(dag.nodes) == 0

    def test_response_field_with_intents(self, decomposer):
        content = json.dumps({
            "intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/x"}, "depends_on": []}],
            "response": "Reading the file for you.",
        })
        dag = decomposer._parse_response(content, "test")
        assert dag.response == "Reading the file for you."
        assert len(dag.nodes) == 1

    def test_response_field_missing_defaults_empty(self, decomposer):
        content = json.dumps({"intents": []})
        dag = decomposer._parse_response(content, "test")
        assert dag.response == ""

    def test_response_field_non_string_ignored(self, decomposer):
        content = json.dumps({"intents": [], "response": 42})
        dag = decomposer._parse_response(content, "test")
        assert dag.response == ""

    def test_json_in_code_fences_with_response(self, decomposer):
        content = '```json\n{"intents": [], "response": "I can only do file operations."}\n```'
        dag = decomposer._parse_response(content, "test")
        assert dag.response == "I can only do file operations."


class TestReflectFieldParsing:
    """Test that the 'reflect' field is extracted from LLM JSON output."""

    @pytest.fixture
    def decomposer(self):
        return IntentDecomposer(
            llm_client=MockLLMClient(),
            working_memory=WorkingMemoryManager(),
        )

    def test_reflect_field_default_false(self):
        dag = TaskDAG()
        assert dag.reflect is False

    def test_reflect_field_set_true(self):
        dag = TaskDAG(reflect=True)
        assert dag.reflect is True

    def test_reflect_field_extracted_true(self, decomposer):
        content = json.dumps({
            "intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp"}, "depends_on": []}],
            "reflect": True,
        })
        dag = decomposer._parse_response(content, "what is the largest file?")
        assert dag.reflect is True
        assert len(dag.nodes) == 1

    def test_reflect_field_extracted_false(self, decomposer):
        content = json.dumps({
            "intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/x"}, "depends_on": []}],
            "reflect": False,
        })
        dag = decomposer._parse_response(content, "read the file")
        assert dag.reflect is False

    def test_reflect_field_missing_defaults_false(self, decomposer):
        content = json.dumps({"intents": []})
        dag = decomposer._parse_response(content, "test")
        assert dag.reflect is False

    def test_reflect_field_non_bool_coerced(self, decomposer):
        content = json.dumps({"intents": [], "reflect": 1})
        dag = decomposer._parse_response(content, "test")
        assert dag.reflect is True

    @pytest.mark.asyncio
    async def test_reflect_method_returns_text(self, decomposer):
        """The reflect() method should return a non-empty synthesis string."""
        result = {
            "dag": TaskDAG(nodes=[
                TaskNode(id="t1", intent="list_directory", params={"path": "/tmp"}, status="completed"),
            ]),
            "results": {"t1": {"success": True}},
        }
        reflection = await decomposer.reflect("what is the largest file?", result)
        assert isinstance(reflection, str)
        assert len(reflection) > 0


class TestReflectHardening:
    """Tests for reflect timeout, payload cap, and exception fallback."""

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager()

    @pytest.fixture
    def decomposer(self, llm, wm):
        return IntentDecomposer(llm_client=llm, working_memory=wm, timeout=2.0)

    @pytest.mark.asyncio
    async def test_reflect_payload_truncated(self, decomposer, llm):
        """Payloads exceeding REFLECT_PAYLOAD_BUDGET are truncated."""
        # Build a result set large enough to exceed the budget.
        # Use many nodes so the combined summary exceeds the budget
        # (each node's result is summarized to ~500 chars).
        nodes = []
        results = {}
        for i in range(30):
            nid = f"t{i}"
            nodes.append(
                TaskNode(id=nid, intent="list_directory", params={"path": f"/tmp/{i}"}, status="completed"),
            )
            results[nid] = {"success": True, "data": "x" * 1000}
        result = {
            "dag": TaskDAG(nodes=nodes),
            "results": results,
        }
        await decomposer.reflect("what files?", result)

        # The last request prompt should have been truncated
        last = llm.last_request
        assert last is not None
        assert len(last.prompt) <= decomposer.REFLECT_PAYLOAD_BUDGET + 50  # +margin for suffix
        assert "[... results truncated ...]" in last.prompt


# ---------------------------------------------------------------------------
# Capability-gap detection
# ---------------------------------------------------------------------------

class TestCapabilityGapDetection:
    """Tests for is_capability_gap() — distinguishes capability-gap responses
    from genuine conversational replies."""

    @pytest.mark.parametrize(
        "text",
        [
            "I don't have a translation capability",
            "I can't translate text into Japanese",
            "I'm unable to perform this operation",
            "No built-in capability for code compilation",
            "Translation is not supported",
            "This is beyond my capabilities",
            "I don't have the ability to do that",
            "There is no native support for that feature",
            "I cannot perform web searches",
            "I lack the necessary tools for that",
            "ProbOS doesn't have a mechanism for that",
            "That is outside my scope",
            "I can help with file operations, but I don't have a translation tool",
            "Sorry, there's no way to do that currently",
            "That capability is not available right now",
            "I doesn't support image generation",  # doesn't have
        ],
    )
    def test_detects_capability_gap(self, text: str) -> None:
        from probos.cognitive.decomposer import is_capability_gap

        assert is_capability_gap(text) is True, f"Expected gap for: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "Hello! I'm ProbOS, your probabilistic operating system.",
            "Here's what I found in the file:",
            "The current time in Tokyo is 1:38 AM.",
            "I can read files, write files, search, and run commands.",
            "",
            "Sure, I'd be happy to help with that!",
            "The file contains 42 lines of Python code.",
            "Done! The file has been written successfully.",
        ],
    )
    def test_rejects_conversational_reply(self, text: str) -> None:
        from probos.cognitive.decomposer import is_capability_gap

        assert is_capability_gap(text) is False, f"False positive for: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "I don\u2019t have an intent for translation yet.",
            "I can\u2019t translate text into Japanese",
            "ProbOS doesn\u2019t have a mechanism for that",
            "I don\u2019t have the ability to do that",
        ],
    )
    def test_detects_capability_gap_unicode_apostrophe(self, text: str) -> None:
        """Unicode curly apostrophes (U+2019) must also trigger capability gap."""
        from probos.cognitive.decomposer import is_capability_gap

        assert is_capability_gap(text) is True, f"Expected gap for: {text!r}"


class TestCapabilityGapFlag:
    """Tests for the structured capability_gap boolean in TaskDAG."""

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager()

    @pytest.fixture
    def decomposer(self, llm, wm):
        return IntentDecomposer(llm_client=llm, working_memory=wm, timeout=2.0)

    @pytest.mark.asyncio
    async def test_capability_gap_flag_parsed_from_json(self, decomposer, llm):
        """_parse_response extracts capability_gap=true from LLM JSON."""
        llm.set_default_response(json.dumps({
            "intents": [],
            "response": "I don't have an intent for translation yet.",
            "capability_gap": True,
        }))
        dag = await decomposer.decompose("please convert this audio to text")
        assert dag.capability_gap is True
        assert dag.response == "I don't have an intent for translation yet."
        assert len(dag.nodes) == 0

    @pytest.mark.asyncio
    async def test_capability_gap_flag_defaults_false(self, decomposer, llm):
        """capability_gap defaults to False when not present in JSON."""
        llm.set_default_response(json.dumps({
            "intents": [],
            "response": "Hello! I'm ProbOS.",
        }))
        dag = await decomposer.decompose("hello")
        assert dag.capability_gap is False

    @pytest.mark.asyncio
    async def test_capability_gap_flag_false_for_normal_intents(self, decomposer, llm):
        """Normal intent decomposition has capability_gap=False."""
        llm.set_default_response(json.dumps({
            "intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/x"}}],
            "reflect": False,
        }))
        dag = await decomposer.decompose("read /tmp/x")
        assert dag.capability_gap is False
        assert len(dag.nodes) == 1

    @pytest.mark.asyncio
    async def test_think_tags_stripped_before_json_extraction(self, decomposer, llm):
        """qwen-style <think>...</think> tags are stripped before JSON parsing."""
        response_with_think = (
            '<think>\nThe user wants to translate text. '
            'I should return {"capability_gap": true} since there is no '
            'translation intent.\n</think>\n\n'
            '{"intents": [], "response": "I don\\u2019t have a translation intent.", '
            '"capability_gap": true}'
        )
        llm.set_default_response(response_with_think)
        dag = await decomposer.decompose("please convert this audio to text")
        assert dag.capability_gap is True
        assert "translation" in dag.response
        assert len(dag.nodes) == 0

    @pytest.mark.asyncio
    async def test_think_tags_with_code_fenced_json(self, decomposer, llm):
        """<think> tags + markdown code fence around JSON still parses."""
        response = (
            '<think>\nLet me analyze this request.\n</think>\n\n'
            '```json\n'
            '{"intents": [{"id": "t1", "intent": "read_file", '
            '"params": {"path": "/tmp/a.txt"}}], "reflect": false}\n'
            '```'
        )
        llm.set_default_response(response)
        dag = await decomposer.decompose("read /tmp/a.txt")
        assert len(dag.nodes) == 1
        assert dag.nodes[0].intent == "read_file"

    @pytest.mark.asyncio
    async def test_think_tags_with_braces_in_reasoning(self, decomposer, llm):
        """<think> block containing { chars doesn't corrupt extraction."""
        response = (
            '<think>\nI need to return something like '
            '{"intents": [], "response": "..."} but with capability_gap. '
            'Let me format it properly.\n</think>\n\n'
            '{"intents": [], "response": "No capability for this.", '
            '"capability_gap": true}'
        )
        llm.set_default_response(response)
        dag = await decomposer.decompose("do something weird")
        assert dag.capability_gap is True
        assert len(dag.nodes) == 0


# ---------------------------------------------------------------------------
# Reflect hardening (continued — timeout, exception, success)
# ---------------------------------------------------------------------------

class TestReflectHardeningExtended:
    """Reflect tests that were originally part of TestReflectHardening."""

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager()

    @pytest.fixture
    def decomposer(self, llm, wm):
        return IntentDecomposer(llm_client=llm, working_memory=wm, timeout=2.0)

    @pytest.mark.asyncio
    async def test_reflect_timeout_returns_empty(self):
        """reflect() returns empty string when the LLM call times out."""
        import asyncio

        class SlowLLM(MockLLMClient):
            async def complete(self, request):
                await asyncio.sleep(10)
                return await super().complete(request)

        decomposer = IntentDecomposer(
            llm_client=SlowLLM(),
            working_memory=WorkingMemoryManager(),
            timeout=0.1,
        )
        result = {
            "dag": TaskDAG(nodes=[
                TaskNode(id="t1", intent="list_directory", params={"path": "/tmp"}, status="completed"),
            ]),
            "results": {"t1": {"success": True}},
        }
        reflection = await decomposer.reflect("largest file?", result)
        assert reflection == ""

    @pytest.mark.asyncio
    async def test_reflect_exception_fallback_in_runtime(self, tmp_path):
        """Runtime sets fallback string when reflect raises an exception."""

        class ExplodingLLM(MockLLMClient):
            _call_count = 0

            async def complete(self, request):
                self._call_count += 1
                # Explode only on the reflect call (2nd call)
                if self._call_count > 1:
                    raise RuntimeError("LLM on fire")
                return await super().complete(request)

        from probos.runtime import ProbOSRuntime

        llm = ExplodingLLM()
        # Pre-set a response with reflect=True
        llm.set_default_response(json.dumps({
            "intents": [{"id": "t1", "intent": "list_directory", "params": {"path": str(tmp_path)}, "depends_on": [], "use_consensus": False}],
            "reflect": True,
        }))
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        try:
            result = await rt.process_natural_language("what is in the dir?")
            # Execution results should still be intact
            assert result["node_count"] == 1
            assert result["completed_count"] == 1
            # Reflection should be the fallback string
            assert "Reflection unavailable" in result["reflection"]
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_reflect_success_unchanged(self, decomposer):
        """Normal reflect still works after hardening — no regressions."""
        result = {
            "dag": TaskDAG(nodes=[
                TaskNode(id="t1", intent="list_directory", params={"path": "/tmp"}, status="completed"),
            ]),
            "results": {"t1": {"success": True, "data": ["a.txt", "b.txt"]}},
        }
        reflection = await decomposer.reflect("what files are in /tmp?", result)
        assert isinstance(reflection, str)
        assert len(reflection) > 0
        assert "agent results" in reflection.lower()


class TestConversationContext:
    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager()

    @pytest.fixture
    def decomposer(self, llm, wm):
        return IntentDecomposer(llm_client=llm, working_memory=wm)

    @pytest.mark.asyncio
    async def test_conversation_context_in_prompt(self, decomposer, llm):
        """Conversation history should appear in the LLM prompt."""
        history = [
            ("user", "What is the weather in Seattle?"),
            ("system", "The weather in Seattle is 72F, partly cloudy."),
        ]
        await decomposer.decompose(
            "What about Portland?",
            conversation_history=history,
        )
        prompt = llm._call_log[-1].prompt
        assert "CONVERSATION CONTEXT" in prompt
        assert "User: What is the weather in Seattle?" in prompt
        assert "ProbOS: The weather in Seattle is 72F, partly cloudy." in prompt
        assert "What about Portland?" in prompt

    @pytest.mark.asyncio
    async def test_conversation_context_truncation(self, decomposer, llm):
        """Long messages in conversation history should be truncated to 200 chars."""
        long_message = "A" * 300
        history = [("system", long_message)]
        await decomposer.decompose("summarize", conversation_history=history)
        prompt = llm._call_log[-1].prompt
        # Should contain truncated version (200 chars + "...")
        assert "A" * 200 + "..." in prompt
        assert "A" * 300 not in prompt

    @pytest.mark.asyncio
    async def test_conversation_context_optional(self, decomposer, llm):
        """Decompose without conversation_history still works (backward compat)."""
        dag = await decomposer.decompose("read the file at /tmp/test.txt")
        assert dag is not None
        prompt = llm._call_log[-1].prompt
        assert "CONVERSATION CONTEXT" not in prompt


# ---------------------------------------------------------------------------
# Ship's Computer Identity tests (AD-317)
# ---------------------------------------------------------------------------


class TestShipsComputerIdentity:
    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager()

    @pytest.fixture
    def decomposer(self, llm, wm):
        return IntentDecomposer(llm_client=llm, working_memory=wm)

    def _make_descriptors(self):
        """Create a set of test descriptors spanning all tiers."""
        return [
            IntentDescriptor(
                name="read_file",
                params={"path": "<absolute_path>"},
                description="Read a file",
                tier="core",
            ),
            IntentDescriptor(
                name="system_health",
                params={},
                description="Get system health",
                tier="utility",
            ),
            IntentDescriptor(
                name="build_code",
                params={"title": "str"},
                description="Generate code changes",
                tier="domain",
                requires_consensus=True,
            ),
        ]

    @pytest.mark.asyncio
    async def test_identity_preamble_in_prompt(self, decomposer, llm):
        """System prompt contains Ship's Computer identity when descriptors are set."""
        decomposer.refresh_descriptors(self._make_descriptors())
        await decomposer.decompose("hello")
        system_prompt = llm._call_log[-1].system_prompt
        assert "Ship's Computer" in system_prompt

    @pytest.mark.asyncio
    async def test_grounding_rules_in_prompt(self, decomposer, llm):
        """System prompt contains GROUNDING RULES when descriptors are set."""
        decomposer.refresh_descriptors(self._make_descriptors())
        await decomposer.decompose("hello")
        system_prompt = llm._call_log[-1].system_prompt
        assert "GROUNDING RULES" in system_prompt

    @pytest.mark.asyncio
    async def test_system_configuration_section(self, decomposer, llm):
        """System Configuration section shows correct tier counts."""
        descriptors = self._make_descriptors()  # 1 core, 1 utility, 1 domain
        decomposer.refresh_descriptors(descriptors)
        await decomposer.decompose("hello")
        system_prompt = llm._call_log[-1].system_prompt
        assert "System Configuration" in system_prompt
        assert "3 registered capabilities" in system_prompt
        assert "1 core" in system_prompt
        assert "1 utility" in system_prompt
        assert "1 domain" in system_prompt
        assert "1 require consensus" in system_prompt

    @pytest.mark.asyncio
    async def test_runtime_summary_in_user_prompt(self, decomposer, llm):
        """Runtime summary appears as SYSTEM CONTEXT in user prompt."""
        decomposer.refresh_descriptors(self._make_descriptors())
        await decomposer.decompose(
            "how healthy is the system?",
            runtime_summary="Active pools: 5, Total agents: 12\nDepartments: Bridge, Engineering",
        )
        prompt = llm._call_log[-1].prompt
        assert "SYSTEM CONTEXT" in prompt
        assert "Active pools: 5" in prompt
        assert "Departments: Bridge, Engineering" in prompt

    @pytest.mark.asyncio
    async def test_runtime_summary_absent_when_none(self, decomposer, llm):
        """SYSTEM CONTEXT does not appear when runtime_summary is None."""
        decomposer.refresh_descriptors(self._make_descriptors())
        await decomposer.decompose("hello")
        prompt = llm._call_log[-1].prompt
        assert "SYSTEM CONTEXT" not in prompt

    @pytest.mark.asyncio
    async def test_hello_example_no_confabulation(self, decomposer, llm):
        """System prompt does not contain confabulating capability claims."""
        decomposer.refresh_descriptors(self._make_descriptors())
        await decomposer.decompose("hello")
        system_prompt = llm._call_log[-1].system_prompt
        confabulations = [
            "search the web",
            "check weather",
            "manage your notes",
            "set reminders",
            "manage notes and todos",
        ]
        for phrase in confabulations:
            assert phrase not in system_prompt, f"Confabulation found: {phrase!r}"

    @pytest.mark.asyncio
    async def test_legacy_prompt_unchanged(self, decomposer, llm):
        """Legacy prompt (no descriptors) does NOT contain Ship's Computer."""
        # Do NOT refresh descriptors — use the legacy path
        await decomposer.decompose("hello")
        system_prompt = llm._call_log[-1].system_prompt
        assert "Ship's Computer" not in system_prompt

    def test_build_runtime_summary(self):
        """_build_self_model returns structured self-knowledge snapshot (AD-318)."""
        import time
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock(spec=ProbOSRuntime)

        # Set up pools
        pool1 = MagicMock()
        pool1.current_size = 3
        pool1.agent_type = "file_reader"
        pool2 = MagicMock()
        pool2.current_size = 2
        pool2.agent_type = "shell"
        runtime.pools = {"filesystem": pool1, "shell": pool2}

        # Pool groups
        group = MagicMock()
        group.display_name = "Engineering"
        group.pool_names = ["filesystem", "shell"]
        runtime.pool_groups = MagicMock()
        runtime.pool_groups.all_groups.return_value = [group]

        # Decomposer descriptors
        runtime.decomposer = MagicMock()
        runtime.decomposer._intent_descriptors = [MagicMock(), MagicMock(), MagicMock()]

        # Health state (AD-318)
        runtime._start_time = time.monotonic() - 120
        runtime._last_request_time = time.monotonic()
        runtime._recent_errors = []
        runtime._last_capability_gap = ""
        runtime.dream_scheduler = MagicMock()
        runtime.dream_scheduler.is_dreaming = False

        # Call the real method on the mock
        model = ProbOSRuntime._build_system_self_model(runtime)
        summary = model.to_context()
        assert "ProbOS" in summary
        assert "Pools: 2" in summary
        assert "Agents: 5" in summary
        assert "Engineering" in summary
        assert "Intents: 3" in summary


class TestSystemSelfModel:
    """Tests for AD-318 SystemSelfModel dataclass and runtime integration."""

    def test_self_model_dataclass_defaults(self):
        """SystemSelfModel defaults are all zero/empty."""
        from probos.cognitive.self_model import SystemSelfModel
        m = SystemSelfModel()
        assert m.pool_count == 0
        assert m.agent_count == 0
        assert m.pools == []
        assert m.departments == []
        assert m.intent_count == 0
        assert m.system_mode == "active"
        assert m.uptime_seconds == 0.0
        assert m.recent_errors == []
        assert m.last_capability_gap == ""

    def test_to_context_minimal(self):
        """Minimal SystemSelfModel produces compact context string."""
        from probos.cognitive.self_model import SystemSelfModel
        m = SystemSelfModel()
        ctx = m.to_context()
        assert "ProbOS" in ctx
        assert "Mode: active" in ctx
        assert "Pools: 0" in ctx
        assert "Agents: 0" in ctx

    def test_to_context_full(self):
        """Fully populated SystemSelfModel includes all sections."""
        from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel
        m = SystemSelfModel(
            version="v0.4.0",
            pool_count=2,
            agent_count=5,
            pools=[
                PoolSnapshot(name="filesystem", agent_type="file_reader", agent_count=3, department="Engineering"),
                PoolSnapshot(name="shell", agent_type="shell", agent_count=2, department="Engineering"),
            ],
            departments=["Engineering", "Science"],
            intent_count=38,
            system_mode="idle",
            uptime_seconds=3600,
            recent_errors=["timeout"],
            last_capability_gap="run docker",
        )
        ctx = m.to_context()
        assert "v0.4.0" in ctx
        assert "Mode: idle" in ctx
        assert "60m" in ctx
        assert "\u00d7" in ctx  # × in pool roster
        assert "Engineering" in ctx
        assert "Science" in ctx
        assert "run docker" in ctx
        assert "timeout" in ctx

    def test_pool_snapshot_fields(self):
        """PoolSnapshot stores all fields correctly."""
        from probos.cognitive.self_model import PoolSnapshot
        p = PoolSnapshot(name="builder", agent_type="builder", agent_count=1, department="Engineering")
        assert p.name == "builder"
        assert p.agent_type == "builder"
        assert p.agent_count == 1
        assert p.department == "Engineering"

    def test_build_self_model(self):
        """_build_self_model returns a fully populated SystemSelfModel."""
        import time
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock(spec=ProbOSRuntime)

        pool1 = MagicMock()
        pool1.current_size = 3
        pool1.agent_type = "file_reader"
        pool2 = MagicMock()
        pool2.current_size = 2
        pool2.agent_type = "shell"
        runtime.pools = {"filesystem": pool1, "shell": pool2}

        group = MagicMock()
        group.display_name = "Engineering"
        group.pool_names = ["filesystem", "shell"]
        runtime.pool_groups = MagicMock()
        runtime.pool_groups.all_groups.return_value = [group]

        runtime.decomposer = MagicMock()
        runtime.decomposer._intent_descriptors = [MagicMock(), MagicMock(), MagicMock()]

        runtime._start_time = time.monotonic() - 120
        runtime._last_request_time = time.monotonic()
        runtime._recent_errors = ["err1"]
        runtime._last_capability_gap = "deploy"
        runtime.dream_scheduler = MagicMock()
        runtime.dream_scheduler.is_dreaming = False

        model = ProbOSRuntime._build_system_self_model(runtime)
        assert model.pool_count == 2
        assert model.agent_count == 5
        assert model.system_mode == "active"
        assert len(model.pools) == 2
        assert any("Engineering" in d for d in model.departments)
        assert model.recent_errors == ["err1"]
        assert model.last_capability_gap == "deploy"
        assert model.uptime_seconds > 0

    def test_build_self_model_dreaming_mode(self):
        """Dreaming scheduler sets system_mode to 'dreaming'."""
        import time
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.pools = {}
        runtime.pool_groups = MagicMock()
        runtime.pool_groups.all_groups.return_value = []
        runtime.decomposer = MagicMock()
        runtime.decomposer._intent_descriptors = []
        runtime._start_time = time.monotonic() - 60
        runtime._last_request_time = time.monotonic()
        runtime._recent_errors = []
        runtime._last_capability_gap = ""
        runtime.dream_scheduler = MagicMock()
        runtime.dream_scheduler.is_dreaming = True

        model = ProbOSRuntime._build_system_self_model(runtime)
        assert model.system_mode == "dreaming"

    def test_build_self_model_idle_mode(self):
        """Idle mode when last request was over 30s ago."""
        import time
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.pools = {}
        runtime.pool_groups = MagicMock()
        runtime.pool_groups.all_groups.return_value = []
        runtime.decomposer = MagicMock()
        runtime.decomposer._intent_descriptors = []
        runtime._start_time = time.monotonic() - 120
        runtime._last_request_time = time.monotonic() - 60  # Over 30s threshold
        runtime._recent_errors = []
        runtime._last_capability_gap = ""
        runtime.dream_scheduler = MagicMock()
        runtime.dream_scheduler.is_dreaming = False

        model = ProbOSRuntime._build_system_self_model(runtime)
        assert model.system_mode == "idle"

    def test_record_error_caps_at_five(self):
        """_record_error keeps only last 5 errors."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime._recent_errors = []

        for _ in range(7):
            ProbOSRuntime._record_error(runtime, "err")

        assert len(runtime._recent_errors) == 5
        assert all(e == "err" for e in runtime._recent_errors)

    def test_to_context_stays_compact(self):
        """Even with 20 pools and 5 errors, context stays under 1000 chars."""
        from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel
        m = SystemSelfModel(
            version="v0.4.0",
            pool_count=20,
            agent_count=100,
            pools=[
                PoolSnapshot(name=f"pool_{i}", agent_type=f"type_{i}", agent_count=5)
                for i in range(20)
            ],
            departments=["Eng", "Sci", "Med", "Sec", "Ops"],
            intent_count=50,
            system_mode="active",
            uptime_seconds=7200,
            recent_errors=["err1", "err2", "err3", "err4", "err5"],
            last_capability_gap="a very long capability gap description here",
        )
        ctx = m.to_context()
        assert len(ctx) < 1000


class TestPreResponseVerification:
    """Tests for AD-319 _verify_response() method."""

    @staticmethod
    def _make_model():
        from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel
        return SystemSelfModel(
            pool_count=14,
            agent_count=54,
            pools=[
                PoolSnapshot(name="filesystem", agent_type="file_reader", agent_count=3, department="Engineering"),
                PoolSnapshot(name="shell", agent_type="shell", agent_count=2, department="Engineering"),
                PoolSnapshot(name="medical", agent_type="vitals_monitor", agent_count=1, department="Medical"),
            ],
            departments=["Engineering", "Medical", "Science"],
            intent_count=38,
            system_mode="active",
            uptime_seconds=3600,
        )

    def test_clean_response_unchanged(self):
        """Response with no verifiable claims passes through unchanged."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "Hello, Captain. How may I assist you?"
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert result == text

    def test_empty_response_unchanged(self):
        """Empty and whitespace-only responses pass through unchanged."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        assert ProbOSRuntime._verify_response(runtime, "", model) == ""
        assert ProbOSRuntime._verify_response(runtime, "   ", model) == "   "

    def test_wrong_pool_count_flagged(self):
        """Wrong pool count adds correction footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "I currently manage 25 pools across the system."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" in result
        assert "14 pools" in result

    def test_correct_pool_count_not_flagged(self):
        """Correct pool count does not add footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "I currently manage 14 pools."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" not in result

    def test_wrong_agent_count_flagged(self):
        """Wrong agent count adds correction footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "There are 200 agents deployed."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" in result
        assert "54 agents" in result

    def test_fabricated_department_flagged(self):
        """Fabricated department name adds footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "The Navigation department handles routing."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" in result

    def test_known_department_not_flagged(self):
        """Known department name does not add footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "The Engineering department handles file operations."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" not in result

    def test_fabricated_pool_flagged(self):
        """Fabricated pool name adds footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "Data is routed through the warpcore pool for processing."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" in result

    def test_known_pool_not_flagged(self):
        """Known pool name does not add footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "The filesystem pool handles file reads."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" not in result

    def test_mode_contradiction_flagged(self):
        """Mode contradiction adds footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()  # system_mode="active"
        text = "The system is idle right now."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" in result
        assert "mode active" in result

    def test_mode_correct_not_flagged(self):
        """Correct mode mention does not add footnote."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "The system is active."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" not in result

    def test_multiple_violations_all_reported(self):
        """Multiple violations produce correction with all facts."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "I have 99 pools and 500 agents. The Navigation department is online."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" in result
        assert "14 pools" in result
        assert "54 agents" in result

    def test_verification_logs_warning(self, caplog):
        """Verification logs a warning when violations are found."""
        import logging
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        with caplog.at_level(logging.WARNING, logger="probos.runtime"):
            ProbOSRuntime._verify_response(runtime, "I have 99 pools.", model)
        assert any("violation" in r.message for r in caplog.records)

    def test_generic_pool_word_not_flagged(self):
        """Generic words like 'agent' in 'the agent pool' are not flagged."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime
        runtime = MagicMock(spec=ProbOSRuntime)
        model = self._make_model()
        text = "The agent pool is doing well."
        result = ProbOSRuntime._verify_response(runtime, text, model)
        assert "[Note:" not in result


class TestIntrospectionDelegation:
    """Tests for AD-320 introspection delegation with grounded context."""

    @staticmethod
    def _make_mock_runtime(
        pool_count=2,
        agent_count=5,
        departments=None,
        recent_errors=None,
        last_capability_gap="",
        intent_descriptors=None,
    ):
        """Build a mock runtime for introspection grounded context tests."""
        import time
        from unittest.mock import MagicMock
        from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel

        if departments is None:
            departments = ["Engineering"]

        pools = []
        mock_pools = {}
        if pool_count >= 1:
            pools.append(PoolSnapshot(name="filesystem", agent_type="file_reader", agent_count=3, department="Engineering"))
            p1 = MagicMock()
            p1.current_size = 3
            p1.agent_type = "file_reader"
            p1.healthy_agents = []
            p1.target_size = 3
            mock_pools["filesystem"] = p1
        if pool_count >= 2:
            pools.append(PoolSnapshot(name="shell", agent_type="shell", agent_count=2, department="Engineering"))
            p2 = MagicMock()
            p2.current_size = 2
            p2.agent_type = "shell"
            p2.healthy_agents = []
            p2.target_size = 2
            mock_pools["shell"] = p2

        model = SystemSelfModel(
            pool_count=pool_count,
            agent_count=agent_count,
            pools=pools,
            departments=departments,
            intent_count=len(intent_descriptors) if intent_descriptors else 0,
            system_mode="active",
            uptime_seconds=120,
            recent_errors=recent_errors or [],
            last_capability_gap=last_capability_gap,
        )

        rt = MagicMock()
        rt._build_system_self_model.return_value = model
        rt.pools = mock_pools
        rt.decomposer = MagicMock()
        rt.decomposer._intent_descriptors = intent_descriptors or []

        # Registry, trust, etc. for handle_intent tests
        rt.registry = MagicMock()
        rt.registry.all.return_value = []
        rt.registry.count = agent_count
        rt.trust_network = MagicMock()
        rt.trust_network.all_scores.return_value = {}
        rt.hebbian_router = MagicMock()
        rt.hebbian_router.all_weights_typed.return_value = {}
        rt.hebbian_router.weight_count = 0
        rt.pool_groups = MagicMock()
        rt.pool_groups.all_groups.return_value = []
        rt.pool_groups.get_group.return_value = None
        rt.attention = MagicMock()
        rt.attention.queue_size = 0
        rt.workflow_cache = None
        rt.dream_scheduler = None
        rt._knowledge_store = None
        rt._emergent_detector = None
        rt._previous_execution = None
        rt.episodic_memory = None

        return rt

    def test_grounded_context_includes_topology(self):
        """Grounded context includes pool and agent counts."""
        from probos.agents.introspect import IntrospectionAgent
        rt = self._make_mock_runtime()
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        ctx = agent._grounded_context()
        assert "Total pools: 2" in ctx
        assert "Total agents: 5" in ctx
        assert "Engineering" in ctx
        assert "filesystem" in ctx
        assert "shell" in ctx

    def test_grounded_context_includes_departments(self):
        """Grounded context includes multiple departments."""
        from probos.agents.introspect import IntrospectionAgent
        rt = self._make_mock_runtime(departments=["Engineering", "Science"])
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        ctx = agent._grounded_context()
        assert "Engineering" in ctx
        assert "Science" in ctx

    def test_grounded_context_includes_intents(self):
        """Grounded context includes intent listing."""
        from probos.agents.introspect import IntrospectionAgent
        from probos.types import IntentDescriptor
        descs = [
            IntentDescriptor(name="list_directory", params={}, description="list dir"),
            IntentDescriptor(name="read_file", params={}, description="read file"),
            IntentDescriptor(name="web_search", params={}, description="web search"),
        ]
        rt = self._make_mock_runtime(intent_descriptors=descs)
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        ctx = agent._grounded_context()
        assert "Available intents:" in ctx
        assert "list_directory" in ctx
        assert "read_file" in ctx
        assert "web_search" in ctx

    def test_grounded_context_includes_health(self):
        """Grounded context includes health signals."""
        from probos.agents.introspect import IntrospectionAgent
        rt = self._make_mock_runtime(
            recent_errors=["timeout"],
            last_capability_gap="deploy app",
        )
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        ctx = agent._grounded_context()
        assert "Recent errors" in ctx
        assert "timeout" in ctx
        assert "capability gap" in ctx
        assert "deploy app" in ctx

    def test_grounded_context_no_runtime_returns_empty(self):
        """No runtime returns empty string."""
        from probos.agents.introspect import IntrospectionAgent
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = None
        assert agent._grounded_context() == ""

    def test_grounded_context_groups_pools_by_department(self):
        """Pools are grouped by department in grounded context."""
        from probos.agents.introspect import IntrospectionAgent
        from probos.cognitive.self_model import PoolSnapshot, SystemSelfModel

        model = SystemSelfModel(
            pool_count=3,
            agent_count=6,
            pools=[
                PoolSnapshot(name="filesystem", agent_type="file_reader", agent_count=3, department="Engineering"),
                PoolSnapshot(name="shell", agent_type="shell", agent_count=2, department="Engineering"),
                PoolSnapshot(name="diagnostician", agent_type="diag", agent_count=1, department="Medical"),
            ],
            departments=["Engineering", "Medical"],
            system_mode="active",
            uptime_seconds=60,
        )
        from unittest.mock import MagicMock
        rt = MagicMock()
        rt._build_system_self_model.return_value = model
        rt.decomposer = MagicMock()
        rt.decomposer._intent_descriptors = []

        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        ctx = agent._grounded_context()
        # Engineering line should have filesystem and shell
        lines = ctx.split("\n")
        eng_line = [l for l in lines if l.strip().startswith("Engineering:")]
        med_line = [l for l in lines if l.strip().startswith("Medical:")]
        assert len(eng_line) == 1
        assert "filesystem" in eng_line[0]
        assert "shell" in eng_line[0]
        assert len(med_line) == 1
        assert "diagnostician" in med_line[0]

    def test_reflect_prompt_has_grounded_context_rule(self):
        """REFLECT_PROMPT contains grounded_context grounding rule."""
        from probos.cognitive.decomposer import REFLECT_PROMPT
        assert "grounded_context" in REFLECT_PROMPT
        assert "VERIFIED SYSTEM FACTS" in REFLECT_PROMPT

    def test_summarize_preserves_grounded_context(self):
        """_summarize_node_result preserves grounded_context outside truncation."""
        from unittest.mock import MagicMock
        from probos.cognitive.decomposer import _summarize_node_result

        ir = MagicMock()
        ir.result = {
            "agents": [{"id": "a1"}],
            "grounded_context": "Total pools: 14\nTotal agents: 54",
        }
        ir.error = None
        node_result = {"success": True, "results": [ir]}
        summary = _summarize_node_result(node_result)
        assert "GROUNDED SYSTEM FACTS" in summary
        assert "Total pools: 14" in summary

    def test_summarize_without_grounded_context_unchanged(self):
        """_summarize_node_result without grounded_context has no GROUNDED section."""
        from unittest.mock import MagicMock
        from probos.cognitive.decomposer import _summarize_node_result

        ir = MagicMock()
        ir.result = {"agents": [{"id": "a1"}]}
        ir.error = None
        node_result = {"success": True, "results": [ir]}
        summary = _summarize_node_result(node_result)
        assert "GROUNDED SYSTEM FACTS" not in summary

    @pytest.mark.asyncio
    async def test_agent_info_includes_grounded_context(self):
        """agent_info handler includes grounded_context in output."""
        from probos.agents.introspect import IntrospectionAgent
        from probos.types import IntentMessage
        rt = self._make_mock_runtime()
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        intent = IntentMessage(id="t1", intent="agent_info", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "grounded_context" in result.result

    @pytest.mark.asyncio
    async def test_system_health_includes_grounded_context(self):
        """system_health handler includes grounded_context in output."""
        from probos.agents.introspect import IntrospectionAgent
        from probos.types import IntentMessage
        rt = self._make_mock_runtime()
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        intent = IntentMessage(id="t1", intent="system_health", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "grounded_context" in result.result

    @pytest.mark.asyncio
    async def test_team_info_includes_grounded_context(self):
        """team_info handler includes grounded_context in output."""
        from probos.agents.introspect import IntrospectionAgent
        from probos.types import IntentMessage
        rt = self._make_mock_runtime()
        agent = IntrospectionAgent(agent_id="test-introsp")
        agent._runtime = rt
        intent = IntentMessage(id="t1", intent="team_info", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "grounded_context" in result.result
