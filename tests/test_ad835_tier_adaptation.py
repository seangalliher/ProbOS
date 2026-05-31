"""AD-835 (Wave 202): per-tier system-prompt adaptation hook.

Covers:
  - CognitiveConfig per-tier suffix fields default to None (zero-config no-op)
  - tier_config(tier) carries the resolved suffix under "system_prompt_suffix"
  - _call_openai appends the suffix to the composed system message only
    (both the prompt-synthesis branch and the pre-built messages branch)
  - The suffix is never applied to user or tool messages
  - During fallback the suffix follows the ATTEMPT tier, not the requested tier
"""

from __future__ import annotations

import json

import httpx
import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import CognitiveConfig
from probos.types import LLMRequest


def _ok_response(_request: httpx.Request) -> httpx.Response:
    """A minimal valid OpenAI chat/completions success body."""
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "ok"}}]},
    )


def _recorder(sink: list[httpx.Request]):
    """Return a MockTransport handler that records every request."""

    def _handle(request: httpx.Request) -> httpx.Response:
        sink.append(request)
        return _ok_response(request)

    return _handle


def _mock_http_client(sink: list[httpx.Request]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://test.local/v1",
        transport=httpx.MockTransport(_recorder(sink)),
        timeout=5.0,
    )


def _payload(sink: list[httpx.Request]) -> dict:
    """Decode the captured chat/completions JSON payload."""
    assert sink, "no request was recorded"
    return json.loads(sink[-1].content)


@pytest.mark.asyncio
async def test_default_suffix_is_noop_system_message_unchanged():
    """No suffix → the composed system message is byte-identical to the input."""
    cfg = CognitiveConfig()
    client = OpenAICompatibleClient(config=cfg)
    try:
        sink: list[httpx.Request] = []
        http = _mock_http_client(sink)
        try:
            request = LLMRequest(prompt="hello", system_prompt="BASE PROMPT", tier="standard")
            await client._call_openai(
                request, model="m", client=http, timeout=5.0,
                effective_system_suffix=None,
            )
        finally:
            await http.aclose()

        messages = _payload(sink)["messages"]
        assert messages[0] == {"role": "system", "content": "BASE PROMPT"}
        assert messages[1] == {"role": "user", "content": "hello"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_suffix_appended_in_prompt_synthesis_branch():
    """system_prompt set (no pre-built messages) → suffix appended to system."""
    cfg = CognitiveConfig()
    client = OpenAICompatibleClient(config=cfg)
    try:
        sink: list[httpx.Request] = []
        http = _mock_http_client(sink)
        try:
            request = LLMRequest(prompt="hello", system_prompt="BASE PROMPT", tier="standard")
            await client._call_openai(
                request, model="m", client=http, timeout=5.0,
                effective_system_suffix="TIER ADDENDUM",
            )
        finally:
            await http.aclose()

        messages = _payload(sink)["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "BASE PROMPT\n\nTIER ADDENDUM"
        # User message is untouched.
        assert messages[1] == {"role": "user", "content": "hello"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_suffix_appended_in_prebuilt_messages_branch():
    """Pre-built request.messages with a leading system message → suffix appended."""
    cfg = CognitiveConfig()
    client = OpenAICompatibleClient(config=cfg)
    try:
        sink: list[httpx.Request] = []
        http = _mock_http_client(sink)
        original = [
            {"role": "system", "content": "PREBUILT SYSTEM"},
            {"role": "user", "content": "describe this"},
        ]
        try:
            request = LLMRequest(prompt="", tier="standard", messages=list(original))
            await client._call_openai(
                request, model="m", client=http, timeout=5.0,
                effective_system_suffix="TIER ADDENDUM",
            )
        finally:
            await http.aclose()

        messages = _payload(sink)["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "PREBUILT SYSTEM\n\nTIER ADDENDUM"
        # Caller's original message dicts are not mutated.
        assert original[0] == {"role": "system", "content": "PREBUILT SYSTEM"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_suffix_not_applied_to_user_or_tool_messages():
    """No system message present → suffix becomes a fresh head system message;
    user and tool messages are never carriers of the suffix."""
    cfg = CognitiveConfig()
    client = OpenAICompatibleClient(config=cfg)
    try:
        sink: list[httpx.Request] = []
        http = _mock_http_client(sink)
        original = [
            {"role": "user", "content": "do a thing"},
            {"role": "tool", "content": "tool output"},
        ]
        try:
            request = LLMRequest(prompt="", tier="standard", messages=list(original))
            await client._call_openai(
                request, model="m", client=http, timeout=5.0,
                effective_system_suffix="TIER ADDENDUM",
            )
        finally:
            await http.aclose()

        messages = _payload(sink)["messages"]
        # Fresh system message inserted at the head.
        assert messages[0] == {"role": "system", "content": "TIER ADDENDUM"}
        # User and tool messages carry no suffix text.
        assert messages[1] == {"role": "user", "content": "do a thing"}
        assert messages[2] == {"role": "tool", "content": "tool output"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_fallback_uses_attempt_tier_suffix():
    """deep unreachable → standard serves the request → standard's suffix ships,
    not deep's. The suffix follows the ATTEMPT tier during fallback."""
    cfg = CognitiveConfig(
        llm_base_url_fast="http://fast.local/v1",
        llm_model_fast="fast-model",
        llm_base_url_deep="http://deep.local/v1",
        llm_model_deep="deep-model",
        llm_base_url_standard="http://standard.local/v1",
        llm_model_standard="standard-model",
        llm_system_prompt_suffix_deep="DEEP SUFFIX",
        llm_system_prompt_suffix_standard="STANDARD SUFFIX",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        recorded: list[httpx.Request] = []

        def _dispatch(request: httpx.Request) -> httpx.Response:
            # Only the standard endpoint succeeds; deep (requested) and fast
            # (next in the text fallback chain) both fail, forcing standard
            # to serve the request.
            recorded.append(request)
            if "standard.local" in str(request.url):
                return _ok_response(request)
            return httpx.Response(503, text="down")

        for key in list(client._clients.keys()):
            existing = client._clients[key]
            await existing.aclose()
            client._clients[key] = httpx.AsyncClient(
                base_url=existing.base_url,
                transport=httpx.MockTransport(_dispatch),
                timeout=5.0,
            )

        request = LLMRequest(prompt="hi", system_prompt="BASE", tier="deep")
        response = await client.complete(request)

        # The request was served (by the standard fallback tier).
        assert response.content == "ok"
        # The standard endpoint received the request with standard's suffix.
        standard_reqs = [r for r in recorded if "standard.local" in str(r.url)]
        assert standard_reqs, "standard tier was never reached"
        payload = json.loads(standard_reqs[-1].content)
        system_msg = payload["messages"][0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == "BASE\n\nSTANDARD SUFFIX"
        assert "DEEP SUFFIX" not in system_msg["content"]
    finally:
        await client.close()


def test_config_suffix_defaults_none_on_zero_config_boot():
    """Zero-config CognitiveConfig: every per-tier suffix is None and
    tier_config carries None under "system_prompt_suffix"."""
    cfg = CognitiveConfig()
    assert cfg.llm_system_prompt_suffix_fast is None
    assert cfg.llm_system_prompt_suffix_standard is None
    assert cfg.llm_system_prompt_suffix_deep is None
    assert cfg.llm_system_prompt_suffix_vision is None
    for tier in ("fast", "standard", "deep", "vision"):
        assert cfg.tier_config(tier).get("system_prompt_suffix") is None
