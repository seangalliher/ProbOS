"""Tests for intent decomposition and DAG execution."""

import json

import pytest

from probos.cognitive.decomposer import IntentDecomposer, DAGExecutor
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.types import LLMRequest, LLMResponse, TaskDAG, TaskNode


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
