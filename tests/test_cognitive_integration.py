"""Integration tests for cognitive pipeline — NL → DAG → mesh + consensus."""

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime


@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with MockLLMClient, start it, yield, stop."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


class TestCognitiveIntegration:
    @pytest.mark.asyncio
    async def test_nl_single_read(self, runtime, tmp_path):
        """NL 'read the file at ...' → single read_file intent → results."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello from probos")

        result = await runtime.process_natural_language(
            f"read the file at {test_file}"
        )

        assert result["node_count"] == 1
        assert result["completed_count"] == 1
        assert result["failed_count"] == 0
        assert result["complete"]

        # Check that actual file content was read
        node_result = result["results"].get("t1", {})
        assert node_result.get("success") is True

    @pytest.mark.asyncio
    async def test_nl_parallel_reads(self, runtime, tmp_path):
        """NL 'read X and Y' → two parallel read_file intents."""
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("content_a")
        file_b.write_text("content_b")

        result = await runtime.process_natural_language(
            f"read {file_a} and {file_b}"
        )

        assert result["node_count"] == 2
        assert result["completed_count"] == 2
        assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_nl_write_with_consensus(self, runtime, tmp_path):
        """NL 'write X to Y' → write_file intent with consensus gate."""
        out_file = tmp_path / "out.txt"

        result = await runtime.process_natural_language(
            f"write hello to {out_file}"
        )

        assert result["node_count"] == 1
        # The write goes through consensus pipeline
        assert result["complete"]

    @pytest.mark.asyncio
    async def test_nl_unrecognized_returns_empty(self, runtime):
        """Unrecognized NL input returns empty DAG without errors."""
        result = await runtime.process_natural_language(
            "what is the meaning of life?"
        )

        assert result["node_count"] == 0
        assert result["complete"]

    @pytest.mark.asyncio
    async def test_nl_read_missing_file(self, runtime, tmp_path):
        """NL read of a missing file → completed DAG but failed intent."""
        result = await runtime.process_natural_language(
            f"read the file at {tmp_path}/nonexistent.txt"
        )

        assert result["node_count"] == 1
        # Agents respond with failure, but the DAG node still completes
        assert result["complete"]

    @pytest.mark.asyncio
    async def test_working_memory_updated(self, runtime, tmp_path):
        """After NL processing, working memory should have recorded results."""
        test_file = tmp_path / "wm_test.txt"
        test_file.write_text("test content")

        await runtime.process_natural_language(
            f"read the file at {test_file}"
        )

        assert len(runtime.working_memory._recent_results) > 0

    @pytest.mark.asyncio
    async def test_status_includes_cognitive(self, runtime):
        """Status should include cognitive section."""
        status = runtime.status()
        assert "cognitive" in status
        assert status["cognitive"]["llm_client"] == "MockLLMClient"
        assert status["cognitive"]["working_memory_budget"] == 4000

    @pytest.mark.asyncio
    async def test_multiple_nl_requests(self, runtime, tmp_path):
        """Multiple NL requests should work sequentially."""
        f1 = tmp_path / "f1.txt"
        f2 = tmp_path / "f2.txt"
        f1.write_text("first")
        f2.write_text("second")

        r1 = await runtime.process_natural_language(f"read the file at {f1}")
        r2 = await runtime.process_natural_language(f"read the file at {f2}")

        assert r1["completed_count"] == 1
        assert r2["completed_count"] == 1
        # Working memory should have accumulated
        assert len(runtime.working_memory._recent_results) == 2
