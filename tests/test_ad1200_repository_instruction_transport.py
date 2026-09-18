"""AD-1200 guidance must survive real transport/cache consumers without log leaks."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.builder import BuildSpec
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
from probos.cognitive.swe_harness.tool_call import ToolUseBlock
from probos.config import CognitiveConfig
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolPermission
from probos.types import LLMRequest, LLMResponse
from tests.test_ad1200_repository_instruction_wire import (
    _AGENT,
    _assert_source_provenance,
    _guidance,
    _repo,
    _runtime,
)


class _MemoryProvider:
    def __init__(self, source: Path | None = None) -> None:
        self.source = source
        self.requests: list[dict[str, Any]] = []
        self.reply = "PROVIDER-COMPLETED"
        self.fail = False
        self.error_body = "OFFLINE-ENDPOINT-ERROR"
        self.retry_marker: str | None = None
        self.malformed_tool_name: str | None = None
        self.transport_error: str | None = None
        self.prompt_tokens: int | str = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "offline.invalid", "A test attempted an unowned endpoint"
        payload = json.loads(request.content)
        self.requests.append(payload)
        if self.transport_error is not None:
            raise httpx.ReadError(self.transport_error, request=request)
        if self.retry_marker is not None:
            return httpx.Response(429, text="busy", headers={"Retry-After": self.retry_marker})
        if self.malformed_tool_name is not None:
            return httpx.Response(200, json={"choices": [{
                "message": {"content": None, "tool_calls": [{
                    "id": "malformed-call",
                    "type": "function",
                    "function": {"name": self.malformed_tool_name, "arguments": "{invalid"},
                }]},
                "finish_reason": "tool_calls",
            }]})
        messages = payload["messages"]
        has_read = any(
            message["role"] == "tool"
            or (message["role"] == "user" and "[tool_result:" in message["content"])
            for message in messages
        )
        if self.source is not None and not has_read:
            return httpx.Response(200, json={
                "choices": [{
                    "message": {"content": None, "tool_calls": [{
                        "id": "stable-file-read",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": str(self.source)}),
                        },
                    }]},
                    "finish_reason": "tool_calls",
                }],
                "usage": {"total_tokens": 7, "prompt_tokens": self.prompt_tokens},
            })
        if self.fail:
            return httpx.Response(503, text=self.error_body)
        if request.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={
                "message": {"content": self.reply}, "eval_count": 7,
            })
        return httpx.Response(200, json={
            "choices": [{"message": {"content": self.reply}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 7, "prompt_tokens": self.prompt_tokens},
        })


def _client(
    monkeypatch: pytest.MonkeyPatch,
    provider: _MemoryProvider,
    *,
    rate: int | None = None,
    api_format: str = "openai",
) -> OpenAICompatibleClient:
    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"],
            transport=httpx.MockTransport(provider.handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    config = CognitiveConfig(
        llm_base_url="https://offline.invalid/v1/",
        llm_api_format_fast=api_format,
        llm_api_format_standard=api_format,
        llm_api_format_deep=api_format,
    )
    rate_config = None if rate is None else SimpleNamespace(
        rpm_fast=rate, rpm_standard=rate, rpm_deep=rate, max_wait_seconds=0,
    )
    return OpenAICompatibleClient(config=config, rate_config=rate_config)


class _RecordingClient:
    def __init__(self, client: OpenAICompatibleClient) -> None:
        self.client = client
        self.requests: list[LLMRequest] = []
        self.responses: list[LLMResponse] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        response = await self.client.complete(request, **kwargs)
        self.responses.append(response)
        return response


@pytest.fixture(autouse=True)
def _source_provenance() -> Any:
    yield
    _assert_source_provenance()


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["openai", "ollama"])
async def test_transport_request_and_response_echo_bodies_never_enter_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, api_format: str,
) -> None:
    provider = _MemoryProvider()
    marker = "AD1200-PRIVATE-INSTRUCTION"
    provider.reply = marker + "-ECHO"
    client = _client(monkeypatch, provider, api_format=api_format)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(
                prompt="Read repository rules", system_prompt=marker, tier="standard",
            ))
        assert len(provider.requests) == 1
        assert provider.requests[0]["messages"][0]["content"] == marker
        assert result.content == marker + "-ECHO" and result.error is None
        assert marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["openai", "ollama"])
async def test_transport_http_error_echo_body_is_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, api_format: str,
) -> None:
    provider = _MemoryProvider()
    marker = "AD1200-PRIVATE-ERROR-ECHO"
    provider.fail = True
    provider.error_body = marker
    client = _client(monkeypatch, provider, api_format=api_format)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(
                prompt="Read repository rules", system_prompt=marker, tier="standard",
            ))
        assert provider.requests and result.error and not result.cached
        assert marker in json.dumps(provider.requests[0])
        assert marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", ["rate", "endpoint"])
@pytest.mark.parametrize("current_guidance", ["OLD-RULE", "NEW-RULE", ""])
@pytest.mark.parametrize("structured", [False, True])
async def test_real_fallback_cache_separates_system_guidance(
    monkeypatch: pytest.MonkeyPatch, fallback: str, current_guidance: str, structured: bool,
) -> None:
    provider = _MemoryProvider()
    client = _client(monkeypatch, provider, rate=1 if fallback == "rate" else None)
    messages = [{"role": "user", "content": "IDENTICAL TRANSCRIPT"}] if structured else None
    original = LLMRequest(
        prompt="IDENTICAL TRANSCRIPT", system_prompt="OLD-RULE", tier="standard",
        messages=copy.deepcopy(messages),
    )
    current = LLMRequest(
        prompt=original.prompt, system_prompt=current_guidance, tier="standard",
        messages=copy.deepcopy(messages),
    )
    try:
        warm = await client.complete(original)
        assert warm.content == provider.reply and not warm.cached and len(provider.requests) == 1
        provider.fail = True
        fallback_result = await client.complete(current)
        assert original.prompt == current.prompt and original.messages == current.messages
        expected_hit = not structured and current_guidance == "OLD-RULE"
        assert fallback_result.cached is expected_hit
        if expected_hit:
            assert fallback_result.content == warm.content and fallback_result.error is None
        else:
            assert fallback_result.error and fallback_result.content == ""
        if fallback == "rate":
            assert len(provider.requests) == 1, "The test did not reach pre-transport rate fallback"
        else:
            assert len(provider.requests) > 1, "The test did not reach exhausted endpoint fallback"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cache_key_preserves_exact_legacy_empty_system_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, _MemoryProvider())
    try:
        expected = f"standard:{hash('prompt')}"
        assert client._cache_key("standard", "prompt") == expected
        assert client._cache_key("standard", "prompt", None) == expected
        assert client._cache_key("standard", "prompt", "") == expected
        assert client._cache_key("standard", "prompt", "rules") != expected
        assert client._cache_key("standard", "ab", "c") != client._cache_key("standard", "a", "bc")
        assert client._cache_key("standard", "prompt", "rules") != client._cache_key("fast", "prompt", "rules")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_provider_tool_name_echo_is_not_logged_on_malformed_arguments(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "AD1200-PRIVATE-TOOL-NAME-ECHO"
    provider = _MemoryProvider()
    provider.malformed_tool_name = marker
    client = _client(monkeypatch, provider)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(
                prompt="Inspect source", system_prompt=marker, tools=[],
            ))
        assert len(provider.requests) == 1 and marker in json.dumps(provider.requests[0])
        assert result.content_blocks and result.error is None
        assert isinstance(result.content_blocks[0], ToolUseBlock)
        assert result.content_blocks[0].tool_call.name == marker
        assert marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_provider_retry_after_echo_is_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "AD1200-PRIVATE-RETRY-HEADER-ECHO"
    provider = _MemoryProvider()
    provider.retry_marker = marker
    client = _client(monkeypatch, provider)
    waits: list[float] = []

    async def no_wait(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(prompt="Inspect source", system_prompt=marker))
        assert len(provider.requests) > 1 and waits and result.error
        assert marker in json.dumps(provider.requests[0])
        assert marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_transport_exception_detail_remains_in_returned_error_but_not_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "AD1200-PRIVATE-TRANSPORT-EXCEPTION"
    provider = _MemoryProvider()
    provider.transport_error = marker
    client = _client(monkeypatch, provider)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(prompt="Inspect source", system_prompt=marker))
        assert provider.requests and marker in json.dumps(provider.requests[0])
        assert result.error and marker in result.error
        assert "ReadError" in caplog.text and marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_provider_token_metadata_is_not_logged_during_empty_retry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "AD1200-PRIVATE-TOKEN-METADATA"
    provider = _MemoryProvider()
    provider.reply = ""
    provider.prompt_tokens = marker
    client = _client(monkeypatch, provider)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(prompt="Inspect source", system_prompt=marker))
        assert len(provider.requests) > 1 and result.error
        assert marker in json.dumps(provider.requests[0])
        assert "prompt_tokens_valid=False" in caplog.text
        assert marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_declared_backend_error_result_preserves_error_without_logging_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "AD1200-PRIVATE-BACKEND-ERROR"
    provider = _MemoryProvider()
    provider.reply = marker
    client = _client(monkeypatch, provider)
    original = client._call_openai

    async def backend_error(
        request: LLMRequest, model: str, transport: httpx.AsyncClient, **kwargs: Any,
    ) -> LLMResponse:
        # Exercise the declared error-result contract after an actual transport,
        # rather than pretending the current OpenAI parser emits this field.
        response = await original(request, model, transport, **kwargs)
        response.error = response.content
        return response

    monkeypatch.setattr(client, "_call_openai", backend_error)
    try:
        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.llm_client"):
            result = await client.complete(LLMRequest(prompt="Inspect source", system_prompt=marker))
        assert provider.requests and marker in json.dumps(provider.requests[0])
        assert result.error and marker in result.error
        assert "LLM response error" in caplog.text and marker not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["native", "work_item"])
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("fallback", ["rate", "endpoint"])
@pytest.mark.parametrize("change", ["replace", "delete"])
async def test_actual_harness_and_reader_guidance_cross_transport_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
    structured: bool, fallback: str, change: str,
) -> None:
    repo, source = _repo(tmp_path)
    rules = _guidance(repo, "AGENTS.md", "ORIGINAL-REPOSITORY-RULE")
    runtime = _runtime(tmp_path, structured=structured)
    await runtime.tool_permission_store.issue_grant(_AGENT, "read_file", ToolPermission.READ)
    provider = _MemoryProvider(source if kind == "work_item" else None)
    limit = 3 if kind == "work_item" else 1
    client = _client(monkeypatch, provider, rate=limit if fallback == "rate" else None)
    recorded = _RecordingClient(client)

    async def run() -> None:
        if kind == "native":
            harness = NativeBuilderHarness(
                runtime=runtime, llm_client=recorded,
                tool_executor=ToolExecutor(registry=runtime.tool_registry),
                tool_registry=runtime.tool_registry, structured_tool_messages=structured,
            )
            await harness.run_build(
                BuildSpec(title="Stable build", description="Inspect source", target_files=["src/widget.py"]),
                str(repo), agent_id=_AGENT,
            )
        else:
            await WorkItemAgenticExecutor(llm_client=recorded).run(
                agent_id=_AGENT, instructions="FIXTURE GOVERNANCE",
                task_text="Read the explicitly named source file.", runtime=runtime,
                department="engineering", rank="lieutenant",
            )

    try:
        await run()
        width = 2 if kind == "work_item" else 1
        assert len(recorded.requests) == width
        assert recorded.responses[-1].content == provider.reply
        old_request = recorded.requests[-1]
        assert "ORIGINAL-REPOSITORY-RULE" in old_request.system_prompt
        if kind == "work_item":
            assert "ORIGINAL-REPOSITORY-RULE" not in recorded.requests[0].system_prompt
            transcript = old_request.prompt or json.dumps(old_request.messages)
            assert "alpha" in transcript, "The registered source reader did not run"
        if change == "replace":
            rules.write_text("REPLACEMENT-REPOSITORY-RULE", encoding="utf-8")
        else:
            rules.unlink()
        provider.fail = True
        await run()
        assert len(recorded.requests) == 2 * width
        new_request = recorded.requests[-1]
        assert new_request.prompt == old_request.prompt
        assert new_request.messages == old_request.messages
        assert new_request.system_prompt != old_request.system_prompt
        assert "ORIGINAL-REPOSITORY-RULE" not in new_request.system_prompt
        assert ("REPLACEMENT-REPOSITORY-RULE" in new_request.system_prompt) == (change == "replace")
        assert recorded.responses[-1].error and not recorded.responses[-1].cached
        if fallback == "rate":
            assert len(provider.requests) == 2 * width - 1
        else:
            assert len(provider.requests) > 2 * width - 1
    finally:
        await client.close()
