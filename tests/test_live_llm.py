"""Live LLM integration tests — require a running LLM backend.

These tests call real LLM endpoints (Ollama for fast tier, Copilot proxy
for standard tier) and verify the full parsing/pipeline logic works
end-to-end.  They are skipped by default in CI; run them explicitly:

    uv run pytest tests/test_live_llm.py -m live_llm -v

Prerequisites:
    - Ollama running at localhost:11434 with qwen3.5:35b loaded
    - Copilot proxy running at localhost:8080 (for agent design tests)
"""

from __future__ import annotations

import json
import tempfile

import httpx
import pytest

from probos.config import load_config
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.decomposer import IntentDecomposer, is_capability_gap
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.types import LLMRequest

pytestmark = pytest.mark.live_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_client_and_config():
    config = load_config("config/system.yaml")
    client = OpenAICompatibleClient(config=config.cognitive)
    return client, config


def _ollama_available() -> bool:
    """Return True if the Ollama endpoint responds."""
    try:
        r = httpx.get("http://127.0.0.1:11434/v1/models", timeout=3)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def _copilot_proxy_available() -> bool:
    """Return True if the Copilot proxy responds."""
    try:
        r = httpx.get("http://127.0.0.1:8080/v1/models", timeout=3)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


skip_no_ollama = pytest.mark.skipif(
    not _ollama_available(), reason="Ollama not running at localhost:11434"
)
skip_no_proxy = pytest.mark.skipif(
    not _copilot_proxy_available(), reason="Copilot proxy not running at localhost:8080"
)


# ---------------------------------------------------------------------------
# Raw LLM response tests
# ---------------------------------------------------------------------------

class TestRawLLMResponse:
    """Verify the LLM client returns usable content from each tier."""

    @skip_no_ollama
    async def test_fast_tier_returns_content(self):
        client, _ = _load_client_and_config()
        try:
            request = LLMRequest(
                prompt="Reply with exactly: HELLO",
                tier="fast",
                max_tokens=64,
            )
            response = await client.complete(request)
            assert response.content, "Fast tier returned empty content"
            assert response.error is None
            assert "HELLO" in response.content.upper()
        finally:
            await client.close()

    @skip_no_proxy
    async def test_standard_tier_returns_content(self):
        client, _ = _load_client_and_config()
        try:
            request = LLMRequest(
                prompt="Reply with exactly: HELLO",
                tier="standard",
                max_tokens=64,
            )
            response = await client.complete(request)
            assert response.content, "Standard tier returned empty content"
            assert response.error is None
            assert "HELLO" in response.content.upper()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Decomposer tests
# ---------------------------------------------------------------------------

class TestDecomposerLive:
    """Verify decomposer parsing with real LLM output."""

    @skip_no_ollama
    async def test_read_file_decomposes(self):
        client, _ = _load_client_and_config()
        try:
            wm = WorkingMemoryManager()
            decomposer = IntentDecomposer(llm_client=client, working_memory=wm, timeout=30.0)
            dag = await decomposer.decompose("read the file /tmp/test.txt")
            assert len(dag.nodes) >= 1, f"Expected at least 1 node, got {len(dag.nodes)}"
            assert dag.nodes[0].intent == "read_file"
            assert dag.nodes[0].params.get("path") == "/tmp/test.txt"
        finally:
            await client.close()

    @skip_no_ollama
    async def test_capability_gap_detected(self):
        client, _ = _load_client_and_config()
        try:
            wm = WorkingMemoryManager()
            decomposer = IntentDecomposer(llm_client=client, working_memory=wm, timeout=30.0)
            dag = await decomposer.decompose("translate hello into japanese")
            # Should produce no actionable intents and signal a capability gap
            assert len(dag.nodes) == 0, f"Expected 0 nodes for unhandled intent, got {len(dag.nodes)}"
            gap = dag.capability_gap or (dag.response and is_capability_gap(dag.response))
            assert gap, f"Expected capability_gap=True, got gap={dag.capability_gap}, response={dag.response!r}"
        finally:
            await client.close()

    @skip_no_ollama
    async def test_conversational_is_not_gap(self):
        client, _ = _load_client_and_config()
        try:
            wm = WorkingMemoryManager()
            decomposer = IntentDecomposer(llm_client=client, working_memory=wm, timeout=30.0)
            dag = await decomposer.decompose("hello")
            # Greeting should have a response but NOT be flagged as a capability gap
            assert len(dag.nodes) == 0
            assert dag.response, "Expected a conversational response"
            assert not dag.capability_gap, "Greeting should not be a capability gap"
        finally:
            await client.close()

    @skip_no_ollama
    async def test_multi_intent_dag(self):
        client, _ = _load_client_and_config()
        try:
            wm = WorkingMemoryManager()
            decomposer = IntentDecomposer(llm_client=client, working_memory=wm, timeout=30.0)
            dag = await decomposer.decompose("list the files in /tmp and then read /tmp/test.txt")
            assert len(dag.nodes) >= 2, f"Expected at least 2 nodes, got {len(dag.nodes)}"
            intents = {n.intent for n in dag.nodes}
            assert "list_directory" in intents, f"Expected list_directory in {intents}"
            assert "read_file" in intents, f"Expected read_file in {intents}"
        finally:
            await client.close()

    @skip_no_ollama
    async def test_json_parsing_survives_think_tags(self):
        """Ensure the decomposer handles qwen's <think> tags."""
        client, _ = _load_client_and_config()
        try:
            wm = WorkingMemoryManager()
            decomposer = IntentDecomposer(llm_client=client, working_memory=wm, timeout=30.0)
            # run_command is a known intent — should parse even with think tags
            dag = await decomposer.decompose("what time is it")
            assert dag.nodes or dag.response, "Expected either intents or a response"
            if dag.nodes:
                # Common valid decompositions: run_command for date/time
                assert dag.nodes[0].intent in ("run_command",), \
                    f"Unexpected intent: {dag.nodes[0].intent}"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Intent extraction tests
# ---------------------------------------------------------------------------

class TestExtractUnhandledIntentLive:
    """Verify _extract_unhandled_intent with real LLM."""

    @skip_no_ollama
    async def test_extract_translation_intent(self):
        client, _ = _load_client_and_config()
        try:
            from probos.runtime import ProbOSRuntime
            data_dir = tempfile.mkdtemp(prefix="probos_test_")
            runtime = ProbOSRuntime(data_dir=data_dir, llm_client=client)
            await runtime.start()
            try:
                intent_meta = await runtime._extract_unhandled_intent(
                    "translate hello into japanese"
                )
                assert intent_meta is not None, "_extract_unhandled_intent returned None"
                assert "name" in intent_meta, f"Missing 'name' key: {intent_meta}"
                assert "description" in intent_meta, f"Missing 'description' key: {intent_meta}"
                # Should be a general-purpose name, not language-specific
                assert "japanese" not in intent_meta["name"].lower(), \
                    f"Intent name should be general, got: {intent_meta['name']}"
            finally:
                await runtime.stop()
        finally:
            await client.close()

    @skip_no_ollama
    async def test_extract_summarize_intent(self):
        client, _ = _load_client_and_config()
        try:
            from probos.runtime import ProbOSRuntime
            data_dir = tempfile.mkdtemp(prefix="probos_test_")
            runtime = ProbOSRuntime(data_dir=data_dir, llm_client=client)
            await runtime.start()
            try:
                intent_meta = await runtime._extract_unhandled_intent(
                    "summarize the contents of this document"
                )
                assert intent_meta is not None, "_extract_unhandled_intent returned None"
                assert "name" in intent_meta
                assert "description" in intent_meta
                assert "parameters" in intent_meta
            finally:
                await runtime.stop()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Agent designer tests
# ---------------------------------------------------------------------------

class TestAgentDesignerLive:
    """Verify agent code generation produces valid, parseable Python."""

    @skip_no_proxy
    async def test_design_translate_agent(self):
        client, config = _load_client_and_config()
        try:
            from probos.cognitive.agent_designer import AgentDesigner
            from probos.cognitive.code_validator import CodeValidator

            designer = AgentDesigner(llm_client=client, config=config.self_mod)
            validator = CodeValidator(config=config.self_mod)

            source = await designer.design_agent(
                intent_name="translate_text",
                intent_description="Translates text into a target language",
                parameters={"text": "source text", "target_language": "target language"},
                requires_consensus=False,
            )

            assert source, "Designer returned empty source"
            assert "class TranslateTextAgent" in source or "TranslateText" in source, \
                f"Expected TranslateTextAgent class, got:\n{source[:300]}"

            # Must pass code validation
            errors = validator.validate(source)
            assert not errors, f"Validation errors: {errors}"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Full pipeline test
# ---------------------------------------------------------------------------

class TestFullPipelineLive:
    """End-to-end: NL input through decompose, self-mod, execute."""

    @skip_no_ollama
    @skip_no_proxy
    async def test_self_mod_creates_and_executes_agent(self):
        """Full self-mod pipeline: translate request -> design agent -> execute."""
        client, _ = _load_client_and_config()
        try:
            from probos.runtime import ProbOSRuntime
            data_dir = tempfile.mkdtemp(prefix="probos_test_")
            runtime = ProbOSRuntime(data_dir=data_dir, llm_client=client)
            await runtime.start()
            try:
                result = await runtime.process_natural_language(
                    "translate hello into japanese"
                )

                # The pipeline should have:
                # 1. Detected capability gap
                # 2. Designed a translate_text agent
                # 3. Re-decomposed and executed
                assert result.get("complete"), f"Pipeline did not complete: {result}"
                assert result.get("failed_count", 1) == 0, \
                    f"Pipeline had failures: {result}"

                # Should have at least 1 node (the translate_text intent)
                dag = result.get("dag")
                if dag:
                    assert len(dag.nodes) >= 1, "Expected at least 1 node after self-mod"
            finally:
                await runtime.stop()
        finally:
            await client.close()
