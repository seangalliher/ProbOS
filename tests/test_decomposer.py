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
        """_build_runtime_summary returns pool/agent/department counts."""
        from unittest.mock import MagicMock
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock(spec=ProbOSRuntime)

        # Set up pools
        pool1 = MagicMock()
        pool1.current_size = 3
        pool2 = MagicMock()
        pool2.current_size = 2
        runtime.pools = {"filesystem": pool1, "shell": pool2}

        # Pool groups
        group = MagicMock()
        group.name = "Engineering"
        runtime.pool_groups = MagicMock()
        runtime.pool_groups.all_groups.return_value = [group]

        # Decomposer descriptors
        runtime.decomposer = MagicMock()
        runtime.decomposer._intent_descriptors = [MagicMock(), MagicMock(), MagicMock()]

        # Call the real method on the mock
        summary = ProbOSRuntime._build_runtime_summary(runtime)
        assert "Active pools: 2" in summary
        assert "Total agents: 5" in summary
        assert "Engineering" in summary
        assert "Registered intents: 3" in summary
